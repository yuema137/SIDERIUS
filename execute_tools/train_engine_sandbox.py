import os
import gc
import json
import argparse
import torch
import torch.nn as nn
import numpy as np
import h5py
from tqdm import tqdm
from torch.utils.data import Dataset, DataLoader

# Import your sandboxed components
from models_sandbox import MODEL_REGISTRY, PositionalUNet, AE, TransformerModel
from models_format_sandbox import PUNetConfig, AEConfig, TrainConfig, LossConfig, get_config_class
from loss_models_sandbox import get_criterion

# ==========================================
# 1. Dataset Logic
# ==========================================

class TIDMADDataset(Dataset):
    def __init__(self, fpath: str, fname_list: list, segmentation_size: int, sample_size: int = 20):
        self.filepath = fpath
        self.filelist = fname_list if isinstance(fname_list, list) else [fname_list]
        self.seg_size = segmentation_size
        self.sample_size = sample_size
        self.idict = {}
        self.tdict = {}
        self.class_count = torch.ones(256)
        self.train_events = self.pull_event_from_dir(self.filelist)
        self.size = len(self.train_events)

    def __len__(self): return self.size

    def __getitem__(self, idx):
        filename, row_idx = self.train_events[idx]
        input_data = self.idict[filename][row_idx]
        target_data = self.tdict[filename][row_idx]
        return (input_data.astype(np.int16) + 128), (target_data.astype(np.int16) + 128)

    def get_class_weight(self):
        weights = self.class_count.sum() / (len(self.class_count) * self.class_count)
        weights = weights / weights.sum() * len(self.class_count)
        return weights

    def pull_event_from_dir(self, filelist):
        evlist = []
        for filename in tqdm(filelist, desc="Indexing H5 Data"):
            file_path = os.path.join(self.filepath, filename)
            if not os.path.exists(file_path): continue
            with h5py.File(file_path, 'r') as f:
                alltrain = np.array(f['timeseries']['channel0001']['timeseries']).astype(np.int8)
                alltarget = np.array(f['timeseries']['channel0002']['timeseries']).astype(np.int16)
                num_segments = len(alltrain) // (self.sample_size * self.seg_size)
                random_offset = np.random.randint(0, self.sample_size)
                self.idict[filename] = alltrain[:num_segments * self.sample_size * self.seg_size].reshape(
                    num_segments, self.sample_size, self.seg_size)[:, random_offset, :]
                self.tdict[filename] = alltarget[:num_segments * self.sample_size * self.seg_size].reshape(
                    num_segments, self.sample_size, self.seg_size)[:, random_offset, :].astype(np.int8)
                self.class_count += torch.Tensor(np.bincount(alltarget + 128, minlength=256))
                for i in range(num_segments): evlist.append((filename, i))
                del alltrain, alltarget
                gc.collect()
        return evlist

# ==========================================
# 2. Refactored Training Engine
# ==========================================

def run_experiment(model_cfg, train_cfg: TrainConfig, loss_cfg: LossConfig, data_loader: DataLoader, sandbox_dirs: dict, exp_id:str):
    device = torch.device(train_cfg.device if torch.cuda.is_available() else "cpu")
    
    # Model Initialization
    model_class = MODEL_REGISTRY.get(model_cfg.model_type)
    if model_class is None:
        raise ValueError(f"Model type {model_cfg.model_type} not found in MODEL_REGISTRY")
    
    # Pass loss_type only for AE (as per your current AE implementation)
    if model_cfg.model_type == "fcnet":
        model = model_class(model_cfg, loss_type=loss_cfg.loss_type).to(device)
    else:
        model = model_class(model_cfg).to(device)

    # Criterion Setup
    class_weights = data_loader.dataset.get_class_weight().to(device) if loss_cfg.use_class_weights else None
    criterion = get_criterion(loss_cfg, class_weights)

    # Optimizer Setup
    if train_cfg.optimizer_type == "adamw":
        optimizer = torch.optim.AdamW(model.parameters(), lr=train_cfg.lr, weight_decay=train_cfg.weight_decay)
    elif train_cfg.optimizer_type == "adam":
        optimizer = torch.optim.Adam(model.parameters(), lr=train_cfg.lr)
    else:
        optimizer = torch.optim.SGD(model.parameters(), lr=train_cfg.lr)

    history = []
    for ep in range(train_cfg.epochs):
        model.train()
        batch_losses = []
        for input_batch, target_batch in tqdm(data_loader, desc=f"Epoch {ep}"):
            input_seq = input_batch.to(device)
            target_seq = target_batch.to(device)

            # --- KEY FIX: Type conversion based on LOSS and MODEL requirements ---
            # 1. Input: Based on Architecture
            if model_cfg.model_type == "punet":
                input_seq = input_seq.int() # PUNet expects discrete ADC values for Embedding
            else:
                input_seq = input_seq.float() # AE/FCNet expects floats

            # 2. Target: Based on Loss Type
            if loss_cfg.loss_type in ["ce", "focal", "focal_cw"]:
                target_seq = target_seq.long() # Classification requires Long targets
            else:
                target_seq = target_seq.float() # Regression (smooth_l1) requires Float targets

            optimizer.zero_grad()
            output = model(input_seq)
            loss = criterion(output, target_seq)
            loss.backward()
            optimizer.step()
            batch_losses.append(loss.item())
            
        avg_loss = np.mean(batch_losses)
        history.append(float(avg_loss))
        print(f"Epoch {ep} | Avg Loss: {avg_loss:.6f}")
        
    # Result Summary
    summary = {
        "final_loss": history[-1],
        "loss_history": history,
        "model_params": sum(p.numel() for p in model.parameters() if p.requires_grad)
    }
    
    # --- KEY FIX: Save to TIDMAD_Sandbox/cached_models ---
    save_path = os.path.join(sandbox_dirs['models'], f"model_{model_cfg.model_type}_{exp_id}_agent.pth")
    torch.save(model.state_dict(), save_path)
    print(f"Model saved to: {save_path}")

    del model, optimizer, criterion
    torch.cuda.empty_cache()
    gc.collect()
    return summary

# ==========================================
# 3. Main Entry Point
# ==========================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_cfg", type=str, required=True)
    parser.add_argument("--train_cfg", type=str, required=True)
    parser.add_argument("--loss_cfg", type=str, required=True)
    parser.add_argument("--data_dir", type=str, default="/home/klz/Data/TIDMAD/")
    parser.add_argument("--sandbox_dir", type=str, default="/home/klz/Data/TIDMAD_Sandbox/")
    parser.add_argument("--file_index", type=int, default=0)
    parser.add_argument("--exp_id", type=str, default="default_exp")
    parser.add_argument("--run_name", type=str,  default="test_run",
                        help="Run name for the auto-exploration.")
    args = parser.parse_args()

    # Define standard sandbox structure
    base_sandbox = args.sandbox_dir
    sandbox_dirs = {
        "models": os.path.join(base_sandbox, "cached_models"),
        "results": os.path.join(base_sandbox, "records") # Use records dir for final JSONs
    }
    os.makedirs(sandbox_dirs["models"], exist_ok=True)
    os.makedirs(sandbox_dirs["results"], exist_ok=True)

    with open(args.model_cfg, 'r') as f: m_data = json.load(f)
    with open(args.train_cfg, 'r') as f: t_data = json.load(f)
    with open(args.loss_cfg, 'r') as f: l_data = json.load(f)

    # Initialize Pydantic Configs
    config_class = get_config_class(m_data.get("model_type"))
    if config_class is None:
        raise ValueError(f"Unknown model_type in config: {m_data.get('model_type')}")
    
    model_cfg = config_class(**m_data)
    train_cfg = TrainConfig(**t_data)
    loss_cfg = LossConfig(**l_data)

    dataset = TIDMADDataset(args.data_dir, [f"abra_training_{str(args.file_index).zfill(4)}.h5"], model_cfg.segmentation_size)
    loader = DataLoader(dataset, batch_size=train_cfg.batch_size, shuffle=True, drop_last=True)

    results = run_experiment(model_cfg, train_cfg, loss_cfg, loader, sandbox_dirs, args.exp_id)
    
    # Save final JSON
    final_res_dir = os.path.join(sandbox_dirs['results'], args.run_name)
    os.makedirs(final_res_dir, exist_ok=True)
    
    # use folder to separate runs
    res_filename = f"experiment_results_{model_cfg.model_type}_{args.exp_id}.json"
    res_path = os.path.join(final_res_dir, res_filename)
    
    with open(res_path, "w") as f: 
        json.dump(results, f, indent=4)
    print(f"Results saved to: {res_path}")

if __name__ == "__main__":
    main()
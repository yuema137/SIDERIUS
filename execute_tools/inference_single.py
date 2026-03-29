import numpy as np
import argparse
import torch
import torch.nn as nn
import h5py
from tqdm import tqdm
import gc
import os
import json

# Import your sandboxed components for Agent Mode
from models_sandbox import MODEL_REGISTRY, PositionalUNet, AE
from models_format_sandbox import PUNetConfig, AEConfig, LossConfig, get_config_class
from array2h5 import create_abra_file

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

def get_parser():
    """Defines the argument parser for both Fix and Agent modes."""
    parser = argparse.ArgumentParser(description="Inference with Fixed (Baseline) or Agent mode.")
    parser.add_argument('--mode', type=str, choices=['fix', 'agent'], default='fix')
    parser.add_argument('--data_dir', '-d', type=str, default="/home/klz/Data/TIDMAD/")
    parser.add_argument('--denoising_model', '-m', type=str, default='punet')
    parser.add_argument('--file_index', '-i', type=int, default=6)
    
    # Agent Mode Specific Args
    parser.add_argument('--model_cfg', type=str, help="Path to model config JSON")
    parser.add_argument('--loss_cfg', type=str, help="Path to loss config JSON")
    parser.add_argument('--exp_id', type=str, default="default_run")
    parser.add_argument("--run_name", type=str,  default="test_run",
                        help="Run name for the auto-exploration.")
    parser.add_argument('--model_path', type=str, help="Path to the .pth state_dict")
    parser.add_argument('--output_dir', type=str, default=None,
                        help="Directory to write denoised H5 output. Defaults to data_dir.")
    parser.add_argument('--inference_batch_size', type=int, default=10,
                        help="Number of segments per GPU forward pass. Per-model defaults set in sandbox_executor.py (punet/wavenet/fcnet=25, rnn=10, transformer=1).")
    parser.add_argument('--sample_set_json', type=str, default=None,
                        help="Path to SampleSet JSON for trial mode. Overrides --file_index.")
    return parser

def process_batch(index, inputarr, targetarr, model, args, current_loss_type):
    """
    Refactored batch processor to ensure dimension alignment across all models.
    Minimal change: ensures input is always [Batch, Time] before entering the model.
    """
    # 1. Base Pre-processing (ADC Offset)
    inputarr = inputarr.astype(np.int16) + 128
    targetarr = targetarr.astype(np.int16) + 128
    input_seq = torch.from_numpy(inputarr) # Shape: [1, 1, Time] from main loop

    # 2. KEY FIX: Standardize Dimensions
    # Both PUNet (Embedding) and FCNet (Linear) expect [Batch, Time].
    # We remove the redundant channel dimension [1, 1, Time] -> [1, Time].
    if input_seq.dim() == 3:
        input_seq = input_seq.squeeze(1)

    # 3. Model-Specific Execution & Type Casting
    # The forward contract is [B, T] int64 for all embedding-based models.
    # Only fcnet (AE) uses float input for regression.
    if args.denoising_model == "fcnet":
        input_seq = input_seq.float().to(DEVICE)
    else:
        input_seq = input_seq.long().to(DEVICE)

    with torch.no_grad():
        output = model(input_seq)
        
        # 4. Decoding Output based on Task Type
        if current_loss_type == "smooth_l1":
            # Regression task: Output is already [Batch, Time]
            output_seq = output.detach().cpu().numpy()
        else:
            # Classification task: Output is [Batch, 256, Time]
            # Convert logits to discrete ADC values via Argmax
            output_seq = output.argmax(dim=1).detach().cpu().numpy()
            
    # Return flattened results for H5 assembly
    return index, (output_seq - 128).flatten(), (targetarr - 128).flatten()

def main():
    # 1. Parse arguments locally to avoid NameError scope issues
    parser = get_parser()
    args = parser.parse_args()

    # 2. Model Loading Logic
    if args.mode == 'fix':
        # Baseline / Fixed mode logic remains largely the same
        model_map = {
            "punet": "PUNet_0_20.pth", 
            "fcnet": "FCNet_0_20.pth",
            "transformer": "Transformer_0_20.pth"
        }
        model_file = model_map.get(args.denoising_model)
        if not model_file or not os.path.exists(model_file):
            raise FileNotFoundError(f"Baseline model file {model_file} not found.")
            
        model = torch.load(model_file, map_location=DEVICE, weights_only=False)
        input_size = 40000 # Default baseline size
        current_loss_type = "ce"
    
    else:
        # AGENT MODE: Dynamic loading using Registry and Factory
        if not args.model_cfg or not args.model_path:
            raise ValueError("Agent mode requires --model_cfg and --model_path")
        
        # Load Loss Type from Config
        loss_path = args.loss_cfg if args.loss_cfg else args.model_cfg.replace("model", "loss")
        with open(loss_path, 'r') as f:
            l_data = json.load(f)
        current_loss_type = l_data.get("loss_type", "ce")

        # Load Model Config
        with open(args.model_cfg, 'r') as f:
            m_data = json.load(f)

        # --- MINIMAL CHANGE: Dynamic Initialization ---
        config_class = get_config_class(args.denoising_model)
        model_class = MODEL_REGISTRY.get(args.denoising_model)
        
        if config_class is None or model_class is None:
            raise ValueError(f"Model type '{args.denoising_model}' is not supported in MODEL_REGISTRY")

        # Instantiate Pydantic config and then the Model
        m_cfg = config_class(**m_data)
        
        # Special handling for AE (loss_type injection), others use standard config init
        if args.denoising_model == "fcnet":
            model = model_class(m_cfg, loss_type=current_loss_type).to(DEVICE)
        else:
            model = model_class(m_cfg).to(DEVICE)
            
        # Load weights from the agent's specific experiment run
        model.load_state_dict(torch.load(args.model_path, map_location=DEVICE))
        input_size = m_cfg.segmentation_size

    model.eval()

    # 3. Load sample set if provided (trial mode)
    sample_set = None
    if args.sample_set_json:
        with open(args.sample_set_json, 'r') as f:
            sample_set = json.load(f)

    # Number of raw samples per PSD segment (1 second at 10 MS/s)
    PSD_SEGMENT_LENGTH = 10_000_000

    if sample_set is not None:
        # --- TRIAL MODE: denoise specific segments from multiple files ---
        out_dir = args.output_dir if args.output_dir else args.data_dir
        for file_index_str, psd_segment_indices in sorted(sample_set.items()):
            file_index = int(file_index_str)
            fname = f"abra_validation_{file_index:04d}.h5"
            fpath = os.path.join(args.data_dir, fname)

            if not os.path.exists(fpath):
                print(f"Warning: {fpath} not found, skipping.")
                continue

            with h5py.File(fpath, 'r') as ABRAfile:
                raw_ch1 = np.array(ABRAfile['timeseries']['channel0001']['timeseries'])
                raw_ch2 = np.array(ABRAfile['timeseries']['channel0002']['timeseries'])

            # Extract requested PSD segments and reshape to ML segments
            input_chunks = []
            target_chunks = []
            for psd_idx in psd_segment_indices:
                start = psd_idx * PSD_SEGMENT_LENGTH
                end = start + PSD_SEGMENT_LENGTH
                input_chunks.append(raw_ch1[start:end])
                target_chunks.append(raw_ch2[start:end])

            all_input = np.concatenate(input_chunks)    # flat array
            all_target = np.concatenate(target_chunks)   # flat array

            train_loader = all_input.reshape(-1, 1, input_size)
            target_loader = all_target.reshape(-1, 1, input_size)

            dim1 = train_loader.shape[0]
            denoised = np.zeros((dim1, input_size), dtype=np.int8)
            injected = np.zeros((dim1, input_size), dtype=np.int8)
            bs = args.inference_batch_size

            for i in tqdm(range(0, dim1, bs), desc=f"Inference file {file_index} ({len(psd_segment_indices)} PSD segs)"):
                batch_in  = train_loader[i:i+bs]
                batch_tgt = target_loader[i:i+bs]
                _, dn, ij = process_batch(i, batch_in, batch_tgt, model, args, current_loss_type)
                actual_n = batch_in.shape[0]
                denoised[i:i+actual_n] = dn.reshape(actual_n, input_size)
                injected[i:i+actual_n] = ij.reshape(actual_n, input_size)

            out_name = os.path.join(
                out_dir,
                f"abra_validation_denoised_{args.denoising_model}_{args.run_name}_{args.exp_id}_{file_index:04d}.h5"
            )
            if os.path.exists(out_name):
                os.remove(out_name)
            create_abra_file(out_name, denoised.flatten().astype(np.int8), injected.flatten().astype(np.int8), indexed=False)
            print(f"Trial inference saved: {out_name}")

            del raw_ch1, raw_ch2, all_input, all_target, denoised, injected
            gc.collect()

    else:
        # --- NORMAL MODE: denoise all segments of a single file ---
        fname = f"abra_validation_{str(args.file_index).zfill(4)}.h5"
        fpath = os.path.join(args.data_dir, fname)

        if not os.path.exists(fpath):
            raise FileNotFoundError(f"Validation data missing at {fpath}")

        with h5py.File(fpath, 'r') as ABRAfile:
            alltrain = np.array(ABRAfile['timeseries']['channel0001']['timeseries'])
            alltarget = np.array(ABRAfile['timeseries']['channel0002']['timeseries'])

            # Reshape according to input_size from config
            train_loader = alltrain.reshape(-1, 1, input_size)
            target_loader = alltarget.reshape(-1, 1, input_size)

            dim1 = train_loader.shape[0]
            denoised = np.zeros((dim1, input_size), dtype=np.int8)
            injected = np.zeros((dim1, input_size), dtype=np.int8)
            bs = args.inference_batch_size

            for i in tqdm(range(0, dim1, bs), desc=f"Inference ({args.mode})"):
                batch_in  = train_loader[i:i+bs]
                batch_tgt = target_loader[i:i+bs]
                _, dn, ij = process_batch(i, batch_in, batch_tgt, model, args, current_loss_type)
                actual_n = batch_in.shape[0]
                denoised[i:i+actual_n] = dn.reshape(actual_n, input_size)
                injected[i:i+actual_n] = ij.reshape(actual_n, input_size)

        # 4. Save Output
        idx_str = str(args.file_index).zfill(4)
        out_dir = args.output_dir if args.output_dir else args.data_dir
        if args.mode == 'fix':
            out_name = os.path.join(out_dir, f"abra_validation_denoised_{args.denoising_model}_{idx_str}.h5")
        else:
            out_name = os.path.join(out_dir, f"abra_validation_denoised_{args.denoising_model}_{args.run_name}_{args.exp_id}_{idx_str}.h5")

        # Clean up old files before writing new one
        if os.path.exists(out_name):
            os.remove(out_name)

        create_abra_file(out_name, denoised.flatten().astype(np.int8), injected.flatten().astype(np.int8), indexed=False)
        print(f"Inference complete. Saved to: {out_name}")
    
if __name__ == "__main__":
    main()
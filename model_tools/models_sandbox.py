import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import nn, Tensor
from torch.nn import TransformerEncoder, TransformerEncoderLayer
from torch.utils.data import dataset
import math
from pydantic import BaseModel, Field, field_validator, model_validator 
from typing import List, Literal, Union
from models_format_sandbox import PUNetConfig, AEConfig, TransformerConfig

# Blocks used by networks

class DoubleConv(nn.Module):
    """
    A foundational building block consisting of two consecutive 1D convolutional layers, 
    each followed by Batch Normalization and LeakyReLU activation.
    
    Agent-Adjustable Parameters:
    - kernel_size: Defines the receptive field. Larger values capture broader wave features.
    - padding: Maintains the temporal resolution. Must be tuned with kernel_size to avoid shape mismatch.
    - bias: Toggles the additive bias. Typically False when used with BatchNorm.
    """

    def __init__(self, in_channels, out_channels, mid_channels=None, kernel_size=9, padding=4, bias=False):
        super().__init__()
        if not mid_channels:
            mid_channels = out_channels
        self.double_conv = nn.Sequential(
            nn.Conv1d(in_channels, mid_channels, kernel_size=kernel_size, padding=padding,bias=bias),
            nn.BatchNorm1d(mid_channels),
            nn.LeakyReLU(inplace=True),
            nn.Conv1d(mid_channels, out_channels, kernel_size=kernel_size, padding=padding,bias=bias),
            nn.BatchNorm1d(out_channels),
            nn.LeakyReLU(inplace=True)
        )

    def forward(self, x):
        return self.double_conv(x)

class Down(nn.Module):
    """
    Adjustable parameters for the Agent:
    - stride: The downsampling factor (default 4). 
             Larger stride saves memory but may lose signal resolution.
    - kernel_size, padding, bias: Passed to DoubleConv to define feature extraction.
    """

    def __init__(self, in_channels, out_channels, stride=4, kernel_size=9, padding=4, bias=False):
        super().__init__()
        # pass stride to MaxPool1d，pass kernel size and padding to DoubleConv
        self.maxpool_conv = nn.Sequential(
            nn.MaxPool1d(kernel_size=stride, stride=stride),
            DoubleConv(
                in_channels, 
                out_channels, 
                kernel_size=kernel_size, 
                padding=padding, 
                bias=bias
            )
        )

    def forward(self, x):
        return self.maxpool_conv(x)

class Up(nn.Module):
    """
    Upsampling block that increases temporal resolution.
    
    Agent-Adjustable Parameters:
    - bilinear: If True, uses Upsample (linear mode). If False, uses ConvTranspose1d.
    - stride: The upsampling factor (default 4).
    - kernel_size: Parameters passed to the DoubleConv layer.
    """

    def __init__(self, in_channels, out_channels, bilinear=True, stride=4, kernel_size=9, padding=4, bias=False):
        super().__init__()
        
        # Calculate padding to maintain sequence length: p = (k-1)/2
        padding = (kernel_size - 1) // 2

        if bilinear:
            # For bilinear, we use nn.Upsample which doesn't change channels.
            # The channel reduction happens inside DoubleConv's mid_channels.
            self.up = nn.Upsample(scale_factor=stride, mode='linear', align_corners=True)
            self.conv = DoubleConv(in_channels, out_channels, in_channels // 2, 
                                   kernel_size=kernel_size, padding=padding, bias=bias)
        else:
            # For ConvTranspose1d, it reduces channels by half during the upsampling step.
            self.up = nn.ConvTranspose1d(in_channels, in_channels // 2, kernel_size=stride, stride=stride)
            # After concatenation with skip connection, the input to DoubleConv returns to in_channels logic
            self.conv = DoubleConv(in_channels, out_channels, kernel_size=kernel_size, 
                                   padding=padding, bias=bias)

    def forward(self, x1, x2):
        # x1: incoming feature map from the lower layer
        # x2: skip connection feature map from the downward path
        x1 = self.up(x1)
        
        # Temporal alignment (handling odd lengths or stride mismatches)
        # x.size() -> [Batch, Channel, Length]
        diff = x2.size()[2] - x1.size()[2]
        if diff != 0:
            x1 = F.pad(x1, [diff // 2, diff - diff // 2])
        
        # Concatenate along the channel dimension
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)
    
class OutConv(nn.Module):
    """
    Final output layer that maps feature channels to the physical ADC channel space (256).
    
    Agent-Adjustable Parameters:
    - bias: Toggles the additive bias for the final projection.
    """
    def __init__(self, in_channels, out_channels, bias=True):
        super(OutConv, self).__init__()
        # We keep kernel_size=1 to perform point-wise classification across channels
        self.conv = nn.Sequential(
            torch.nn.Conv1d(in_channels, out_channels, kernel_size=1, bias=bias),
        )

    def forward(self, x):
        return self.conv(x)
    
class PositionalEncoding(nn.Module):
    """
    Injects temporal position information into the latent space. 
    Crucial for phase-coherent dark matter signals.

    Agent-Adjustable Parameters:
    - max_len: Must match the current 'segmentation_size'. Defines the temporal buffer.
    - factor: The strength of positional information.
    - dropout: Regularization strength to prevent the model from over-relying on position.
    """

    def __init__(self, d_model, max_len, start=0, dropout=0.1, factor=1.0):
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)
        self.factor = factor
        self.start = start

        # Generate the sinusoid positional encoding matrix up to max_len
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        
        # Reshape to (1, d_model, max_len) to match Conv1d input format [Batch, Channel, Time]
        pe = pe.unsqueeze(0).transpose(1, 2)
        
        # Register as buffer (fixed during training, moved with model to GPU)
        self.register_buffer('pe', pe)

    def forward(self, x):
        """
        Adds positional encoding to the input tensor.
        x shape: [Batch, d_model, Length]
        """
        # Slice the pre-computed pe buffer to match the input length
        x = x + self.factor * self.pe[:, :, self.start : (self.start + x.size(2))]
        x = self.dropout(x)
        return x
    
class PositionalUNet(nn.Module):
    """
    Dynamic Positional U-Net for Agent Sandbox.
    
    The architecture scales automatically based on the 'depth' parameter.
    Agent can optimize: multi, depth, bilinear, pe_factor, etc.
    """
    def __init__(self, config:PUNetConfig):
        super(PositionalUNet, self).__init__()
        
        # visit properties directly, as the input was valudated by pydantic
        self.multi = config.multi
        self.depth = config.depth
        self.bilinear = config.bilinear
        self.seg_size = config.segmentation_size
        self.pe_factor = config.pe_factor
        self.kernel_size = config.kernel_size
        self.padding = int((self.kernel_size-1) / 2)
        
        adc_channel = 256
        emb_dim = config.embedding_dim

        # 1. Input layers
        self.embedding = nn.Embedding(adc_channel, emb_dim, scale_grad_by_freq=True)
        self.pe_in = PositionalEncoding(emb_dim, max_len=self.seg_size, factor=self.pe_factor)
        self.inc = DoubleConv(emb_dim, self.multi, kernel_size=self.kernel_size, padding=self.padding)
        self.pe_inc = PositionalEncoding(self.multi, max_len=self.seg_size, factor=self.pe_factor)

        # 2. Downward Path (Encoder)
        self.downs = nn.ModuleList()
        self.pe_downs = nn.ModuleList()
        
        curr_ch = self.multi
        for i in range(self.depth):
            out_ch = curr_ch * 2
            # different calculation for bilinear case
            if i == self.depth - 1:
                factor = 2 if self.bilinear else 1
                out_ch = out_ch // factor
            
            self.downs.append(Down(curr_ch, out_ch, kernel_size=self.kernel_size, padding=self.padding))
            self.pe_downs.append(PositionalEncoding(out_ch, max_len=self.seg_size, factor=self.pe_factor))
            curr_ch = out_ch

        # 3. Upward Path (Decoder)
        self.ups = nn.ModuleList()
        self.pe_ups = nn.ModuleList()
        
        # Up: reversal of down
        for i in range(self.depth):
            up_in_ch = curr_ch * 2
            up_out_ch = curr_ch // 2
            # align the top layer output
            if i == self.depth - 1:
                up_out_ch = self.multi // (2 if self.bilinear else 1)
            
            self.ups.append(Up(up_in_ch, up_out_ch, self.bilinear, kernel_size=self.kernel_size, padding=self.padding))
            self.pe_ups.append(PositionalEncoding(up_out_ch, max_len=self.seg_size, factor=self.pe_factor))
            curr_ch = up_out_ch

        # 4. Output layer
        self.outc = OutConv(curr_ch, adc_channel)

    def forward(self, x):
        x = self.embedding(x).transpose(-1, -2)
        x = self.pe_in(x)
        
        # 1. Input layer and first skip
        x1 = self.pe_inc(self.inc(x))
        # store intermediate result for Skip Connection
        skip_outputs = [x1]

        # 2. Downward path
        curr_x = x1
        for i in range(self.depth - 1): # Only store until the second to last layer
            curr_x = self.downs[i](curr_x)
            curr_x = self.pe_downs[i](curr_x)
            skip_outputs.append(curr_x)

        # 3. Bottom layer (no skip storage)
        curr_x = self.downs[-1](curr_x)
        curr_x = self.pe_downs[-1](curr_x)

        # 4. Upward path
        for i in range(self.depth):
            skip_x = skip_outputs.pop()
            curr_x = self.ups[i](curr_x, skip_x)
            curr_x = self.pe_ups[i](curr_x)

        return self.outc(curr_x)
    
class AE(nn.Module):
    """
    Fully Connected AutoEncoder tailored for the Agent Sandbox.
    
    Architecture:
    - Dynamic encoder/decoder based on 'latent_dims'.
    - Final output layer projects back to ADC channel space (256) 
      to match the PositionalUNet's classification behavior.
    """
    def __init__(self, config: AEConfig, loss_type: str = "ce"):
        super().__init__()
        self.input_dim = config.segmentation_size
        self.loss_type = loss_type
        dims = config.latent_dims
        
        encoder_modules = []
        last_dim = self.input_dim
        for d in dims:
            encoder_modules.append(nn.Linear(last_dim, d))
            encoder_modules.append(nn.ReLU())
            if config.dropout > 0: encoder_modules.append(nn.Dropout(config.dropout))
            last_dim = d
        self.encoder = nn.Sequential(*encoder_modules)
        
        decoder_modules = []
        reversed_dims = dims[::-1][1:] + [self.input_dim]
        for d in reversed_dims:
            decoder_modules.append(nn.Linear(last_dim, d))
            if d != self.input_dim:
                decoder_modules.append(nn.ReLU())
            last_dim = d
        self.decoder_base = nn.Sequential(*decoder_modules)
        
        if self.loss_type != "smooth_l1":
            self.outc = nn.Conv1d(1, 256, kernel_size=1)

    def forward(self, x):
        x_float = x.float()
        latent = self.encoder(x_float)
        reconstructed = self.decoder_base(latent) # [Batch, Time]

        if self.loss_type == "smooth_l1":
            return reconstructed
        
        return self.outc(reconstructed.unsqueeze(1))
    
class TransformerModel(nn.Module):
    """
    Refactored Transformer based on baseline training script.
    Maintains the same logic but supports dynamic configuration.
    """
    def __init__(self, config: TransformerConfig):
        super().__init__()
        self.emb_dim = config.embedding_dim
        
        # Use 256 for ADC classes
        self.embedding = nn.Embedding(256, self.emb_dim, scale_grad_by_freq=True)
        
        # Positional encoding: note that your PositionalEncoding class 
        # expects [Batch, Channel, Time]
        self.pos_encoder = PositionalEncoding(
            self.emb_dim, 
            max_len=config.segmentation_size, 
            factor=config.pe_factor,
            dropout=config.dropout
        )
        
        encoder_layers = nn.TransformerEncoderLayer(
            d_model=self.emb_dim, 
            nhead=config.nhead, 
            dim_feedforward=config.dim_feedforward, 
            dropout=config.dropout,
            batch_first=True 
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layers, num_layers=config.num_layers)
        
        # Final projection to 256 ADC channels
        self.linear = nn.Linear(self.emb_dim, 256)

    def forward(self, x):
        # x: [Batch, Time] -> Long for Embedding
        x = self.embedding(x.long()) * math.sqrt(self.emb_dim) # [Batch, Time, Emb]
        
        # Adapt to your PositionalEncoding [Batch, Channel, Time]
        x = x.transpose(1, 2) 
        x = self.pos_encoder(x)
        x = x.transpose(1, 2) # Back to [Batch, Time, Emb]
        
        # Transformer Processing
        output = self.transformer_encoder(x) # [Batch, Time, Emb]
        
        # Output Projection: [Batch, Time, 256]
        output = self.linear(output) 
        
        # Transpose to [Batch, 256, Time] to match Loss requirements
        return output.transpose(1, 2)
    
# 2. Global Registry
MODEL_REGISTRY = {
    "punet": PositionalUNet,
    "fcnet": AE,
    "transformer": TransformerModel,
}
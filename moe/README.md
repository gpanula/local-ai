# Mixture of Experts (MoE) Exploration

This directory contains research, benchmark scripts, and analysis on Mixture of Experts architectures under local hardware constraints (8 GB VRAM Quadro P4200).

## Topics & Artifacts
* Pure in-VRAM MoE testing (`olmoe:7b-instruct`)
* Hybrid GPU + CPU/RAM offloading tests (`mixtral:8x7b`, `phi-3.5-moe`)
* Router dynamics, gating loss, and expert utilization analysis

# AWS Strands Harness

An architectural overview and quick-reference guide for **AWS Strands** and the **Strands Harness** agentic evaluation & orchestration framework.

---

## 🌟 Overview

**AWS Strands** (Strands Agents SDK) is an open-source, model-agnostic agent orchestration library created by AWS to build and execute autonomous AI agents.

Built on top of the SDK, **Strands Harness** provides an out-of-the-box, production-ready agent execution environment that bridges the gap between local prototyping and scalable cloud/enterprise deployment.

---

## 🔑 Core Concepts & Architecture

1. **Model-First Agentic Loop**:
   - Integrates reasoning models with deterministic tools and system prompts in an iterative observe-reason-act-reflect loop.
   - Model-agnostic design: natively supports Amazon Bedrock, Anthropic, OpenAI, Google Gemini, and local models via **Ollama**.

2. **Strands Harness**:
   - Pre-packaged autonomous agent harness providing essential tools out of the box (shell execution, workspace file I/O, web search).
   - Designed to run within the host process without heavyweight external runtime dependencies.

3. **Context & Token Optimization**:
   - Features intelligent context management, tool output offloading, and prompt-caching strategies to reduce token bloat and inference latency.

4. **Strands CLI**:
   - Command-line interface for natural-language agent prototyping, evaluation benchmarks, and exporting workflows to clean Python/TypeScript code.

---

## 🔗 Integration with Local AI

In this repository, Strands Harness principles complement our local Ollama multi-agent pipeline (`Arc-Orc-Rev`):
- **Local Model Delegation**: Can target local Ollama endpoints (`http://127.0.0.1:11434`) for offline evaluation.
- **Tooling Parity**: Uses similar defensive shell execution and sandboxed file I/O patterns matching our project standards (`AGENTS.md`).

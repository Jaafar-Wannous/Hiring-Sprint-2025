# Hiring Sprint 2025 - AI-Powered Vehicle Condition Assessment



## What''s Next (given more time)

1. **Reliability & Observability** - add queue-based processing for large uploads, structured logging, and health probes that validate downstream AI readiness.
2. **Security & Access Control** - introduce auth (tenant API keys or OAuth), signed image URLs, and role-based permissions for fleet partners.
3. **Offline & Mobile UX** - enable PWA capabilities, local caching of pickup sessions, and background upload retries for poor network conditions.
4. **AI Enhancements** - fine-tune YOLO on internal datasets, export ONNX/TensorRT variants for faster inference, and expose a `/metrics` endpoint for precision/recall tracking.
5. **CI/CD & Testing Depth** - wire GitHub Actions to lint/test all services, add FastAPI unit tests plus Angular e2e flows, and publish artifacts to container registries automatically.

Delivering those items would pave the way for customer-ready reporting (PDF export, notifications) and a pricing engine tied to live parts/labor databases.

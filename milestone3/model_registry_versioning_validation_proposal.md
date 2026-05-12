# Model Registry Versioning & Validation Proposal

## Current State

The current model registry already stores:

| Field | Purpose |
|---|---|
| uuid | Unique identifier |
| name | Logical model name |
| type | Model/framework type |
| s3_url | Artifact storage location |
| risks | Governance/risk metadata |

Current limitation:

- No versioning support
- Difficult to support rollback and reproducibility
- No artifact integrity validation
- No immutable artifact tracking
- Difficult to distinguish model artifact changes vs runtime config changes

---

# Goals

The design should:

- Stay simple
- Support all model types generically
- Support LLM multi-file models
- Support Triton layout
- Avoid overcomplicated schemas
- Separate:
  - immutable model artifacts
  - runtime/serving configuration
- Support validation before serving

---

# Proposed Architecture

## Core Mental Model

```text
Model
  ↓
Model Version
  ↓
Serving Config (optional)
  ↓
Deployment
```

---

# 1. Model

Represents the logical model identity.

Example:

```text
fraud-model
recommendation-ranker
llama-3-70b
```

This is essentially the current table.

---

# 2. Model Version

Represents:

> an immutable snapshot of actual model artifact files

## Suggested Fields

| Field | Purpose |
|---|---|
| version_uuid | Unique version id |
| model_uuid | Parent model reference |
| version | Human-readable version |
| artifact_root_uri | Root S3 path |
| artifact_type | triton / huggingface / pytorch / onnx / sklearn |
| artifact_manifest_hash | Overall manifest checksum |
| artifact_manifest_json | File manifest |
| status | registered / validated / production / archived |
| created_by | User or pipeline |
| created_at | Audit timestamp |

---

# 3. Generic Manifest Design

The registry should NOT assume:
- single file models
- Triton structure
- LLM structure

Instead use one generic manifest format.

## Example: ONNX

```json
{
  "files": [
    {
      "path": "model.onnx",
      "sha256": "...",
      "size": 12345
    }
  ]
}
```

---

## Example: LLM

```json
{
  "files": [
    {
      "path": "model-00001-of-00004.safetensors",
      "sha256": "...",
      "size": 123
    },
    {
      "path": "model-00002-of-00004.safetensors",
      "sha256": "...",
      "size": 123
    },
    {
      "path": "tokenizer.json",
      "sha256": "...",
      "size": 123
    },
    {
      "path": "config.json",
      "sha256": "...",
      "size": 123
    }
  ]
}
```

Same schema for all model types.

---

# 4. Triton Handling

## Example Triton Layout

```text
model/
  config.pbtxt
  1/
    model.onnx
```

Important principle:

> `config.pbtxt` changes should NOT automatically create a new model version.

Reason:
- runtime tuning changes are operational
- weights remain identical
- avoids version explosion

---

## Therefore

### Model Version Tracks

Only immutable artifact files:

```text
1/model.onnx
```

---

### Serving Config Tracks

Runtime behavior separately:

```text
config.pbtxt
autoscaling configs
vLLM runtime args
TensorRT runtime configs
```

---

# 5. Optional Serving Config Table

## Suggested Fields

| Field | Purpose |
|---|---|
| config_uuid | Unique config id |
| model_version_uuid | Linked model version |
| config_type | triton / vllm / kserve |
| config_hash | Config integrity |
| config_uri | Optional storage path |
| created_at | Timestamp |

This allows:

```text
Same model version
+ different serving configs
= different deployments
```

Without creating unnecessary model versions.

---

# 6. Validation Design

## Problem

KServe downloads models dynamically using:

```text
storage-initializer
```

Which pulls artifacts from S3 into:

```text
/mnt/models
```

Need to validate:
- integrity
- missing files
- corruption
- accidental changes

Before the predictor container starts.

---

# Recommended Validation Flow

```text
S3 model folder
   ↓
storage-initializer
   ↓
download to /mnt/models
   ↓
model-validator initContainer
   ↓
predictor container starts
```

---

# Recommended Pod Lifecycle

```text
initContainer 1:
  storage-initializer

initContainer 2:
  model-validator

main container:
  predictor
```

The predictor starts ONLY if validation succeeds.

---

# 7. Validation Logic

Validator compares:

```text
/mnt/models
```

Against:

```text
artifact_manifest_json
```

Stored in the registry.

---

## Validation Checks

For each file:

```text
expected path
expected checksum
expected size
```

Validator checks:

- file exists
- checksum matches
- size matches

Optional:
- reject unexpected files

---

# Example Validation

Manifest:

```json
{
  "path": "1/model.onnx",
  "sha256": "abc123",
  "size": 12345
}
```

Validator checks:

```text
/mnt/models/1/model.onnx exists
sha256(local_file) == abc123
size == 12345
```

---

# 8. Manifest Retrieval Options

Validator can retrieve manifest via:

## Option 1

Pass manifest JSON as env var.

Simple but large for LLMs.

---

## Option 2

Mount manifest as ConfigMap/Secret.

---

## Option 3 (Recommended)

Pass:

```text
model_version_uuid
```

Validator calls registry API:

```text
GET /model-versions/{id}/manifest
```

Then validates local files.

Best for:
- scalability
- centralized logic
- future extensibility

---

# 9. Important LLM Considerations

LLMs often contain:

```text
multiple safetensors shards
tokenizers
configs
vocab files
```

Validation should verify ALL immutable files.

Example:

```text
/mnt/models/model-00001-of-00004.safetensors
/mnt/models/model-00002-of-00004.safetensors
/mnt/models/tokenizer.json
/mnt/models/config.json
```

---

# 10. Final Recommendation

## Keep It Simple

The minimal scalable architecture is:

```text
model
  ↓
model_version
  ↓
serving_config (optional)
  ↓
deployment
```

---

## Core Principles

### Model Version

Represents immutable model artifacts.

---

### Serving Config

Represents runtime behavior.

---

### Validation

Happens AFTER storage initialization and BEFORE predictor startup.

---

# Benefits

This design provides:

- immutable version history
- rollback support
- reproducibility
- artifact integrity validation
- generic model support
- clean Triton support
- clean LLM support
- simple schema
- operational flexibility
- alignment with W&B-style artifact thinking

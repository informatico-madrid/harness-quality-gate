# Verdict Schema — Security Finding Resolution

**Purpose:** Formal schema for security finding verdicts produced during Layer 4 Phase 3 (LLM Triage) and Phase 4 (Party Mode). Ensures consistent verdict structure across all agents.

---

## Overview

Each security finding goes through a triage process:

```
Phase 3 (LLM Triage) → verdict ∈ {TRUE_POSITIVE, FALSE_POSITIVE, NEEDS_CONSENSUS}
Phase 4 (Party Mode)  → verdict ∈ {CONFIRMED, REJECTED, ESCALATE_TO_FAIL}
```

---

## Verdict Types

### Phase 3 Verdicts (LLM Triage)

| Verdict | Meaning | Gate Action |
|---------|---------|-------------|
| `TRUE_POSITIVE` | LLM confirms this is a real vulnerability | BLOCK (confirms finding) |
| `FALSE_POSITIVE` | LLM determines this is not a real vulnerability | WARN (downgrade to WARNING) |
| `NEEDS_CONSENSUS` | LLM cannot classify with confidence ≥ threshold | Escalate to Phase 4 (Party Mode) |

### Phase 4 Verdicts (Party Mode)

| Verdict | Meaning | Gate Action |
|---------|---------|-------------|
| `CONFIRMED` | ≥2 of 3 agents agree this is a real vulnerability | BLOCK (confirms finding) |
| `REJECTED` | ≥2 of 3 agents agree this is a false positive | WARN (downgrade to WARNING) |
| `ESCALATE_TO_FAIL` | No consensus after 2 rounds (≤1 agent agrees) | BLOCK (gate fails) |

---

## VerdictSchema Definition

Each verdict must include the following fields:

```yaml
Verdict:
  finding_id: string           # Unique identifier (tool + rule_id + file + line)
  agent: string               # Agent name: "LLM" | "Winston" | "Murat" | "Amelia"
  verdict: string             # Verdict value from the tables above
  confidence: float           # 0.0-1.0 (LLM confidence in classification)
  reasoning: string          # Human-readable explanation of the verdict
  voting_record: array        # History of votes (for Party Mode)
  round: integer             # 1 or 2 (for Party Mode)
  timestamp: string          # ISO 8601 timestamp
```

### Example Verdict (Phase 3 - LLM Triage)

```json
{
  "finding_id": "bandit-B608-emhass_adapter.py-142",
  "agent": "LLM",
  "verdict": "NEEDS_CONSENSUS",
  "confidence": 0.45,
  "reasoning": "The query uses f-string but the source of the variable is unclear. The pattern matches B608 but the actual risk depends on whether user input can reach this code path.",
  "voting_record": [],
  "round": 1,
  "timestamp": "2026-05-04T06:30:00Z"
}
```

### Example Verdict (Phase 4 - Party Mode)

```json
{
  "finding_id": "bandit-B608-emhass_adapter.py-142",
  "agent": "Winston",
  "verdict": "CONFIRMED",
  "confidence": 0.85,
  "reasoning": "The f-string interpolates data directly from hass.states. This is user-controlled data that reaches a database query. Trust boundary violation confirmed.",
  "voting_record": [
    {"round": 1, "verdict": "CONFIRMED", "confidence": 0.85}
  ],
  "round": 1,
  "timestamp": "2026-05-04T06:31:00Z"
}
```

```json
{
  "finding_id": "bandit-B608-emhass_adapter.py-142",
  "agent": "Murat",
  "verdict": "CONFIRMED",
  "confidence": 0.90,
  "reasoning": "Attack surface is limited (requires Home Assistant UI access), but the vulnerability is real. An authenticated attacker could inject via the entity_id parameter.",
  "voting_record": [
    {"round": 2, "verdict": "CONFIRMED", "confidence": 0.90, "saw_winston": "CONFIRMED"}
  ],
  "round": 2,
  "timestamp": "2026-05-04T06:32:00Z"
}
```

```json
{
  "finding_id": "bandit-B608-emhass_adapter.py-142",
  "agent": "Amelia",
  "verdict": "CONFIRMED",
  "confidence": 0.80,
  "reasoning": "Fix is straightforward: use parameterized query. The vulnerability exists and the fix is feasible.",
  "voting_record": [
    {"round": 3, "verdict": "CONFIRMED", "confidence": 0.80, "saw_winston": "CONFIRMED", "saw_murat": "CONFIRMED"}
  ],
  "round": 3,
  "timestamp": "2026-05-04T06:33:00Z"
}
```

### ESCALATE_TO_FAIL Example

```json
{
  "finding_id": "semgrep-js-hardcoded-secret-auth.ts-55",
  "agent": "Winston",
  "verdict": "CONFIRMED",
  "confidence": 0.70,
  "reasoning": "This looks like a test configuration, not a production secret.",
  "voting_record": [{"round": 1, "verdict": "CONFIRMED"}],
  "round": 1,
  "timestamp": "2026-05-04T06:35:00Z"
}
```

```json
{
  "finding_id": "semgrep-js-hardcoded-secret-auth.ts-55",
  "agent": "Murat",
  "verdict": "REJECTED",
  "confidence": 0.65,
  "reasoning": "This is clearly a test fixture, not an actual secret. The pattern matched on 'test_api_key_12345' which is obviously not real.",
  "voting_record": [
    {"round": 2, "verdict": "REJECTED", "confidence": 0.65, "saw_winston": "CONFIRMED"}
  ],
  "round": 2,
  "timestamp": "2026-05-04T06:36:00Z"
}
```

```json
{
  "finding_id": "semgrep-js-hardcoded-secret-auth.ts-55",
  "agent": "Amelia",
  "verdict": "CONFIRMED",
  "confidence": 0.75,
  "reasoning": "Even if it's a test key, the pattern should be refactored to use environment variables. The rule is correctly flagging hardcoded values.",
  "voting_record": [
    {"round": 3, "verdict": "CONFIRMED", "confidence": 0.75, "saw_winston": "CONFIRMED", "saw_murat": "REJECTED"}
  ],
  "round": 3,
  "timestamp": "2026-05-04T06:37:00Z"
}
```

**Consensus result:** 2 CONFIRMED, 1 REJECTED → **CONFIRMED** (majority wins)

### No Consensus (ESCALATE_TO_FAIL)

```json
{
  "finding_id": "checkov-CKV_DOCKER_1-dockerfile-12",
  "agent": "Winston",
  "verdict": "CONFIRMED",
  "confidence": 0.60,
  "reasoning": "The Dockerfile uses an untagged 'python:3.11' base image which could pull different versions.",
  "voting_record": [{"round": 1, "verdict": "CONFIRMED"}],
  "round": 1,
  "timestamp": "2026-05-04T06:40:00Z"
}
```

```json
{
  "finding_id": "checkov-CKV_DOCKER_1-dockerfile-12",
  "agent": "Murat",
  "verdict": "REJECTED",
  "confidence": 0.55,
  "reasoning": "The docker-compose.yml pins the image to a specific SHA. The Dockerfile itself is not the delivery artifact.",
  "voting_record": [
    {"round": 2, "verdict": "REJECTED", "confidence": 0.55, "saw_winston": "CONFIRMED"}
  ],
  "round": 2,
  "timestamp": "2026-05-04T06:41:00Z"
}
```

```json
{
  "finding_id": "checkov-CKV_DOCKER_1-dockerfile-12",
  "agent": "Amelia",
  "verdict": "NEEDS_CONSENSUS",
  "confidence": 0.30,
  "reasoning": "I'm not sure. The pinning is in docker-compose, not in the Dockerfile itself. This seems like a valid concern but I don't have enough context.",
  "voting_record": [
    {"round": 3, "verdict": "NEEDS_CONSENSUS", "confidence": 0.30, "saw_winston": "CONFIRMED", "saw_murat": "REJECTED"}
  ],
  "round": 3,
  "timestamp": "2026-05-04T06:42:00Z"
}
```

**Consensus result:** 1 CONFIRMED, 1 REJECTED, 1 NEEDS_CONSENSUS → **ESCALATE_TO_FAIL** (no majority)

---

## Finding ID Format

```
{tool}-{rule_id}-{file}-{line}
```

Examples:
- `bandit-B608-emhass_adapter.py-142`
- `semgrep-js-hardcoded-secret-auth.ts-55`
- `checkov-CKV_DOCKER_1-dockerfile-12`
- `gitleaks-gitsecrets-secrets.yaml-23`

---

## Usage in Checkpoint

The checkpoint JSON should include verdicts in `layer4_security_defense`:

```json
{
  "layer4_security_defense": {
    "PASS": false,
    "total_findings": 5,
    "confirmed_findings": 2,
    "rejected_findings": 2,
    "escalated_findings": 1,
    "findings": [
      {
        "finding_id": "bandit-B608-emhass_adapter.py-142",
        "verdicts": [
          {"agent": "LLM", "verdict": "NEEDS_CONSENSUS", "confidence": 0.45},
          {"agent": "Winston", "verdict": "CONFIRMED", "confidence": 0.85},
          {"agent": "Murat", "verdict": "CONFIRMED", "confidence": 0.90},
          {"agent": "Amelia", "verdict": "CONFIRMED", "confidence": 0.80}
        ],
        "final_verdict": "CONFIRMED",
        "severity": "HIGH",
        "fix_applied": true
      }
    ]
  }
}
```

# OWASP Top 10 Security Checklist

**Purpose:** Manual security review checklist aligned with OWASP Top 10 (2021). Used as a consultable reference during Phase 3 (LLM Triage) and Phase 4 (Party Mode) of Layer 4.

**How to use:** When a finding mentions an OWASP category, consult this checklist to verify the finding is correctly classified and to identify related vulnerabilities the automated tools may have missed.

---

## Table of Contents

1. [A01:2021 - Broken Access Control](#a012021---broken-access-control)
2. [A02:2021 - Cryptographic Failures](#a022021---cryptographic-failures)
3. [A03:2021 - Injection](#a032021---injection)
4. [A04:2021 - Insecure Design](#a042021---insecure-design)
5. [A05:2021 - Security Misconfiguration](#a052021---security-misconfiguration)
6. [A06:2021 - Vulnerable and Outdated Components](#a062021---vulnerable-and-outdated-components)
7. [A07:2021 - Identification and Authentication Failures](#a072021---identification-and-authentication-failures)
8. [A08:2021 - Software and Data Integrity Failures](#a082021---software-and-data-integrity-failures)
9. [A09:2021 - Security Logging and Monitoring Failures](#a092021---security-logging-and-monitoring-failures)
10. [A10:2021 - Server-Side Request Forgery](#a102021---server-side-request-forgery)

---

## A01:2021 - Broken Access Control

**Description:** Access control enforces policy so that users cannot act outside their intended permissions. Failures typically lead to unauthorized information disclosure, modification, or destruction of data, or execution of business functions.

### Common Vulnerabilities
- Bypass of access control checks by modifying the URL or internal API request
- Allowing viewing or editing someone else's account by providing its unique identifier
- Elevation of privilege (acting as admin when logged in as user)
- Metadata manipulation (JWT attacks)
- CORS misconfiguration allowing unauthorized API access

### Verification Commands

```bash
# Check for missing authorization decorators
grep -rn "requires_auth\|@login_required\|@admin_required" src/

# Check for direct object reference patterns
grep -rn "entity_id\|device_id\|user_id" src/ | grep -v "_id:"

# Check JWT usage for alg:none attacks
grep -rn "jwt\|JWT\|algorithm" src/ | grep -i "none\|algorithm"

# Check CORS configuration
grep -rn "Access-Control" src/ | grep -v "allowed_domains\|cors_allowed_origins"
```

### Example Findings (from a real HA integration)
- **my_adapter.py:** Direct hass.data access without access control checks
- **services.py:** Service handlers without user context validation
- **coordinator.py:** DataUpdateCoordinator without authentication context

---

## A02:2021 - Cryptographic Failures

**Description:** Failures related to cryptography which often lead to sensitive data exposure. Common weaknesses include using deprecated hash functions (MD5, SHA1), weak crypto keys, improper key management, or using encryption where authentication is needed.

### Common Vulnerabilities
- Use of deprecated cryptographic functions (MD5, SHA1 for hashing)
- Insufficient key length
- Hardcoded encryption keys or secrets in source code
- Use of custom cryptographic protocols instead of proven libraries
- Sensitive data transmitted in plain text (HTTP, Telnet)

### Verification Commands

```bash
# Check for hardcoded secrets
grep -rn "password\|secret\|api_key\|token" src/*.py | grep -v "os.environ\|os.getenv"

# Check for weak crypto usage
grep -rn "hashlib\|crypto\|AES\|RSA\|DES\|MD5\|SHA1" src/

# Check for plaintext secrets in logs
grep -rn "logging\|log\." src/ | grep -i "password\|token\|secret\|key"

# Check for HTTP (non-TLS) usage
grep -rn "http://" src/ | grep -v "localhost\|127.0.0.1"
```

### Findings in This Project
- **utils.py:** Potential hardcoded configuration values
- **config_flow.py:** Sensitive data in YAML storage without encryption at rest

---

## A03:2021 - Injection

**Description:** Injection flaws occur when untrusted data is sent to an interpreter as part of a command or query. SQL, NoSQL, OS command, and LDAP injection are common variants.

### Common Vulnerabilities
- SQL injection via string concatenation
- Command injection via os.system(), subprocess with shell=True
- Code injection via eval(), exec(), __import__()
- YAML deserialization attacks (yaml.load without SafeLoader)
- Path traversal via unsanitized file paths

### Verification Commands

```bash
# SQL Injection (Bandit B608 patterns)
python3 -m bandit -r src/ -f json | jq '.results[] | select(.issue_cwe=="CWE-89")'

# Command Injection
grep -rn "subprocess\|os.system\|os.popen\|eval\|exec" src/

# YAML unsafe load
grep -rn "yaml.load\|yaml.safe_load" src/ | grep -v "SafeLoader\|FullLoader"

# Check for path traversal in file operations
grep -rn "open\|read\|write" src/ | grep -E "\(.*\+|\.format\(" | grep -v "safe\|sanitize"
```

### Example Findings (from a real HA integration)
- **my_adapter.py:** SQL-like patterns in energy calculations
- **yaml_storage.py:** YAML deserialization with potential unsafe load

---

## A04:2021 - Insecure Design

**Description:** Insecure design represents weaknesses in design patterns and architectures. It is different from insecure implementation — even a perfect implementation of an insecure design is still insecure.

### Common Vulnerabilities
- Missing authentication/authorization for sensitive operations
- No rate limiting on API endpoints or service calls
- Missing brute-force protection on authentication endpoints
- Trust boundaries not clearly defined between components
- Sensitive data logged or exposed unnecessarily

### Verification Commands

```bash
# Check for missing rate limiting
grep -rn "rate_limit\|throttle\|max_requests" src/

# Check for missing authentication checks in services
grep -rn "hass.auth\|user_id\|current_user" src/services.py

# Check for sensitive data in logs
grep -rn "logging" src/ | grep -E "password|token|secret|api_key|coordinate|location"

# Check for missing input validation
grep -rn "assert\|raise\|ValueError" src/ | grep -v "if\|check\|valid"
```

### Findings in This Project
- **coordinator.py:** DataUpdateCoordinator without input validation on external sensor data
- **trip_manager.py:** Missing validation on trip datetime inputs

---

## A05:2021 - Security Misconfiguration

**Description:** Security misconfiguration is the most commonly seen issue. This is commonly a result of insecure default configurations, incomplete configurations, open cloud storage, misconfigured HTTP headers, or verbose error messages containing sensitive information.

### Common Vulnerabilities
- Missing or misconfigured security headers
- Default credentials left enabled
- Error handling that reveals stack traces or sensitive info
- Overly permissive CORS policies
- Debug features enabled in production

### Verification Commands

```bash
# Check for debug mode in production
grep -rn "debug\|DEBUG" src/ | grep -v "if.*debug\|log.*debug\|logger"

# Check for exposed stack traces in error handlers
grep -rn "except\|traceback\|exc_info" src/ | grep -v "log\|logger\|logging"

# Check for missing security headers in HTTP responses
grep -rn "Content-Security-Policy\|X-Frame-Options\|X-Content-Type" src/

# Check for default HA configuration exposures
grep -rn "allow_backup\|debugger\|profiler" src/manifest.json
```

### Findings in This Project
- **diagnostics.py:** Diagnostic file potentially exposing sensitive Ha data
- **panel.py:** Lovelace panel configuration with potential information disclosure

---

## A06:2021 - Vulnerable and Outdated Components

**Description:** You are likely vulnerable if you do not know the versions of all components you use, if your software is outdated or unsupported, or if you do not scan for vulnerabilities regularly.

### Common Vulnerabilities
- Outdated Python packages with known CVEs
- Use of deprecated APIs or libraries
- Dependencies with transitive vulnerabilities
- Unmaintained open-source components

### Verification Commands

```bash
# Check for outdated packages
pip-audit || safety check

# Check package versions
pip freeze | grep -E "flask|django|jinja|requests|urllib"

# Check for known vulnerable patterns
semgrep --config=p/security-audit src/

# Check for deprecated API usage
grep -rn "warnings.warn\|DeprecationWarning" src/
```

### Example Findings (from a real HA integration)
- **requirements in manifest.json:** Need to verify against latest HA core requirements
- **my_adapter.py:** HTTP client version should be pinned

---

## A07:2021 - Identification and Authentication Failures

**Description:** Confirmation of the user's identity, authentication, and session management is critical. Authentication weaknesses exist when applications permit weak passwords, brute-force attacks, or expose session identifiers.

### Common Vulnerabilities
- Permitting default passwords or known passwords
- Using plain text or weakly hashed passwords
- Missing or ineffective multi-factor authentication
- Exposing session IDs in URLs
- Not properly invalidating session on logout

### Verification Commands

```bash
# Check for hardcoded credentials
grep -rn "password\|passwd\|pwd" src/*.py | grep -v "os.environ\|getenv\|secrets"

# Check for weak session management
grep -rn "session\|Session\|cookie" src/

# Check for exposed tokens in URLs
grep -rn "token\|api_key" src/ | grep -E "url|URL|request|get|post"

# Check for missing logout functionality
grep -rn "logout\|revoke\|invalidate" src/
```

### Findings in This Project
- **yaml_trip_storage.py:** Trip data stored without user-context isolation
- **services.py:** Service calls lack authentication context validation

---

## A08:2021 - Software and Data Integrity Failures

**Description:** Software and data integrity failures relate to code and infrastructure that does not protect against integrity violations. This includes insecure CI/CD pipelines, unverified updates, or code that uses insecure serialization.

### Common Vulnerabilities
- Using untrusted data without integrity checking
- Deserialization of untrusted data (pickle, yaml.load without SafeLoader)
- Auto-apt update without signature verification
- Using plugins from untrusted sources
- Relying on unsigned firmware/software

### Verification Commands

```bash
# Check for pickle deserialization
grep -rn "pickle\|Unpickler" src/

# Check for YAML unsafe loading
grep -rn "yaml.load" src/ | grep -v "SafeLoader"

# Check for unsigned external resources
grep -rn "import\|require\|pip install" src/ | grep -v "requirements"

# Check for git repository integrity
git log --show-signature 2>/dev/null || echo "No signed commits"
```

### Findings in This Project
- **yaml_trip_storage.py:** YAML deserialization of trip data without signature verification

---

## A09:2021 - Security Logging and Monitoring Failures

**Description:** Without logging and monitoring, breaches cannot be detected. Insufficient logging, detection, and response occurs in every incident and is usually not noticed until a third party informs the application of the incident.

### Common Vulnerabilities
- Auditable events (login, logout, access denied) are not logged
- Warnings and errors generate no log messages
- Logs are not monitored for suspicious activity
- Application stores no logs centrally
- Penetration testing does not trigger alerts

### Verification Commands

```bash
# Check for missing audit events
grep -rn "logging\|logger" src/ | grep -E "INFO|ERROR|WARNING" | wc -l

# Check for sensitive data in logs
grep -rn "log\|debug" src/ | grep -iE "password|token|secret|coordinate|lat|lon"

# Check for monitoring gaps
grep -rn "try\|except" src/ | grep -v "log\|logger" | wc -l

# Check for unhandled exceptions
grep -rn "raise\|AssertionError" src/ | grep -v "if\|check\|valid"
```

### Findings in This Project
- **services.py:** Service handlers without audit logging
- **coordinator.py:** DataUpdateCoordinator without error logging

---

## A10:2021 - Server-Side Request Forgery

**Description:** SSRF flaws occur when a web application fetches a remote resource without validating the user-supplied URL. Attackers can force the application to send crafted requests to unexpected destinations, even through firewalls.

### Common Vulnerabilities
- Fetching URLs without validation
- Allowing access to private networks (localhost, internal APIs)
- No allowlist of permitted domains
- Not restricting ports and protocols

### Verification Commands

```bash
# Check for URL fetching without validation
grep -rn "requests\.\|httpx\.\|urllib\|fetch\|curl\|wget" src/

# Check for localhost/internal network access
grep -rn "localhost\|127.0.0.1\|0\.0\.0\.0\|internal\|private" src/

# Check for missing URL validation
grep -rn "verify\|allowlist\|blocklist\|validate.*url" src/

# Check for unrestricted ports
grep -rn ":\|port\|socket" src/ | grep -v "config\|const\|DEFAULT"
```

### Example Findings (from a real HA integration)
- **my_adapter.py:** External API calls without URL validation
- **utils.py:** Potential HTTP client usage with internal URLs

---

## References

- [OWASP Top 10 2021](https://owasp.org/Top10/)
- [CWE Database](https://cwe.mitre.org/)
- [OWASP Testing Guide](https://owasp.org/www-project-web-security-testing-guide/)

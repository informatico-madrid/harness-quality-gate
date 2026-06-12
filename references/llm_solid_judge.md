# SOLID Judge Prompt — BMAD Tier-B Review

> Passed to BMAD Party Mode agents (Winston, Murat, Amelia) for semantic
> SOLID principle evaluation during Layer 3B deep quality checks.

## Evaluation Framework

Evaluate each class/module against the five SOLID principles. Report violations
with severity (HIGH / MEDIUM / LOW) and a one-line fix suggestion.

### S — Single Responsibility Principle

**Rule**: A class should have only one reason to change.

| Red flag | Example |
|----------|---------|
| >7 public methods | Class handles parsing, validation, DB access, and logging |
| Multiple concerns in `__init__` | Sets up DB, email, cache, and queue connections |
| `if/elif` chains by type | Dispatches different logic per data type instead of using polymorphism |

### O — Open/Closed Principle

**Rule**: Open for extension, closed for modification.

| Red flag | Example |
|----------|---------|
| No ABC/Protocol | Adding a new strategy requires editing an if-chain |
| Concrete imports in domain | Domain code imports `MySQLConnection` instead of `DatabaseConnector` |
| No inheritance hierarchy | Every new format is a `elif format == "json":` branch |

### L — Liskov Substitution Principle

**Rule**: Subclasses must be substitutable for their base classes.

| Red flag | Example |
|----------|---------|
| Narrowed return types | Parent returns `str | None`, child returns `str` |
| Strengthened preconditions | Parent accepts `int`, child raises on negatives |
| `isinstance` checks on subclasses | `if isinstance(conn, MySQLConn)` in shared code |

### I — Interface Segregation Principle

**Rule**: No client should be forced to depend on methods it does not use.

| Red flag | Example |
|----------|---------|
| Fat interfaces | `Processor` interface with `process()`, `render()`, `serialize()` |
| Empty method implementations | Class inherits interface but `render()` is `pass` |
| Many unused method stubs | Class has 12 methods, only 3 are called by its clients |

### D — Dependency Inversion Principle

**Rule**: Depend on abstractions, not concretions.

| Red flag | Example |
|----------|---------|
| Direct instantiation | `self.db = MySQLConnection()` instead of injection |
| No DI in constructors | Domain classes call `os.environ` directly for config |
| Circular imports | Module A imports from B, B imports from A |

---

## Python examples

### SRP violation — Multiple responsibilities

```python
# BEFORE: EmailService handles parsing, validation, AND sending
class EmailService:
    def parse_template(self, template: str) -> dict:
        ...
    def validate_address(self, addr: str) -> bool:
        ...
    def send(self, to: str, body: str) -> None:
        ...  # SMTP logic mixed with template parsing

# AFTER: Each class has one responsibility
class TemplateParser:
    def parse(self, template: str) -> dict: ...

class AddressValidator:
    def validate(self, addr: str) -> bool: ...

class EmailSender:
    def send(self, to: str, body: str) -> None: ...
```

### OCP violation — If-chain instead of polymorphism

```python
# BEFORE: Adding a new format requires modifying this function
def export(data: list, fmt: str) -> bytes:
    if fmt == "json":
        return json.dumps(data).encode()
    elif fmt == "csv":
        return "\n".join(",".join(row) for row in data).encode()
    elif fmt == "xml":
        return f"<data>{data}</data>".encode()
    raise ValueError(fmt)

# AFTER: Open for extension, closed for modification
class ExportStrategy(Protocol):
    def export(self, data: list) -> bytes: ...

class JsonExport(ExportStrategy):
    def export(self, data: list) -> bytes: return json.dumps(data).encode()

class CsvExport(ExportStrategy):
    def export(self, data: list) -> bytes: ...
```

### DIP violation — Concrete dependency

```python
# BEFORE: Direct import of concrete class
class OrderProcessor:
    def __init__(self):
        self.db = MySQLConnection("localhost", "orders")  # Hard-coded

# AFTER: Dependency injection
class OrderProcessor:
    def __init__(self, repository: OrderRepository):  # Abstraction
        self.db = repository

# Then: processor = OrderProcessor(MySQLRepository())
```

---

## PHP examples

### SRP violation — Controller doing too much

```php
// BEFORE: UserController handles auth, DB, validation, rendering
class UserController {
    public function store(Request $request) {
        $validator = Validator::make($request->all(), [...]); // Validation
        $user = User::create($request->all());               // DB access
        Auth::login($user);                                   // Auth
        return view('users.show', ['user' => $user]);        // Rendering
    }
}

// AFTER: Separate concerns
class CreateUserRequest extends FormRequest { /* validation */ }
class UserService {
    public function create(array $data): User { /* business logic */ }
}
class UserController {
    public function store(CreateUserRequest $request, UserService $service) {
        return view('users.show', ['user' => $service->create($request->validated())]);
    }
}
```

### LSP violation — Strengthened preconditions

```php
// BEFORE: Child restricts parent contract
abstract class Shape {
    abstract public function area(): float;
}
class Rectangle extends Shape {
    public function area(): float {
        if ($this->width < 0 || $this->height < 0) {
            throw new InvalidArgumentException(); // Parent allows negatives!
        }
        return $this->width * $this->height;
    }
}

// AFTER: Subclass doesn't strengthen preconditions
class Rectangle extends Shape {
    public function area(): float {
        return abs($this->width * $this->height);
    }
}
```

### ISP violation — Fat interface

```php
// BEFORE: One interface forces unused methods
interface Worker {
    public function work(): void;
    public function eat(): void;    // Robot workers don't eat!
    public function sleep(): void;  // Robot workers don't sleep!
}
class RobotWorker implements Worker {
    public function work(): void {}
    public function eat(): void { throw new RuntimeException(); }
    public function sleep(): void { throw new RuntimeException(); }
}

// AFTER: Segregated interfaces
interface Workable {
    public function work(): void;
}
interface Feedable {
    public function eat(): void;
}
class RobotWorker implements Workable {
    public function work(): void {}
}
```

---

## Output Format

Return a JSON object with the following structure:

```json
{
  "language": "python|php",
  "violations": [
    {
      "id": "SRP",
      "class": "EmailService",
      "file": "src/notifications.py",
      "line": 42,
      "severity": "HIGH",
      "description": "Class handles parsing, validation, and sending",
      "fix": "Split into TemplateParser, AddressValidator, EmailSender"
    }
  ],
  "PASS": true,
  "_summary": {
    "total_violations": 2,
    "high": 1,
    "medium": 0,
    "low": 1
  }
}
```

If no violations are found, return:

```json
{
  "language": "python|php",
  "violations": [],
  "PASS": true,
  "_summary": {"total_violations": 0, "high": 0, "medium": 0, "low": 0}
}
```

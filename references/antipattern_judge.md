# Antipattern Judge Prompt — BMAD Tier-B Review

> Passed to BMAD Party Mode agents (Winston, Murat, Amelia) for semantic
> antipattern evaluation during Layer 3B deep quality checks.

## Evaluation Framework

Evaluate each class/module against Tier-B semantic patterns. Report violations
with severity (HIGH / MEDIUM / LOW) and a one-line fix suggestion.

### Key Pattern Families

#### Structural Antipatterns

| ID | Name | Severity | Description |
|----|------|----------|-------------|
| AP14 | Divergent Change | HIGH | One class changed for many different reasons |
| AP15 | Shotgun Surgery | HIGH | One change requires editing many files |
| AP16 | Parallel Inheritance | MEDIUM | Mirrored class hierarchies |
| AP32 | Stovepipe System | HIGH | Hardcoded component connections |
| AP33 | Vendor Lock-In | MEDIUM | Tightly coupled to specific vendor |

#### Code Quality Antipatterns

| ID | Name | Severity | Description |
|----|------|----------|-------------|
| AP19 | Temporary Field | MEDIUM | Instance variables only set conditionally |
| AP27 | Incomplete Library Class | MEDIUM | Extending third-party class |
| AP28 | Comments as Deodorant | LOW | Comments explain bad code instead of fixing it |
| AP29 | Inappropriate Intimacy | MEDIUM | Excessive access to class internals |
| AP34 | Lava Flow | MEDIUM | Dead code from experiments |
| AP35 | Ambiguous Viewpoint | LOW | Mixed abstraction levels in same module |

#### Test Antipatterns

| ID | Name | Severity | Description |
|----|------|----------|-------------|
| AP41 | Hard-Coded Test Data | MEDIUM | Test data embedded in test functions |
| AP43 | Test Code Duplication | MEDIUM | Repeated mock setup across tests |
| AP44 | Test Per Method | HIGH | One test per method, no edge cases |
| AP45 | Mock Object Abuse | HIGH | >80% of test code is mock setup |
| AP47 | Eager Test | MEDIUM | One test verifies multiple behaviors |

#### Design Antipatterns

| ID | Name | Severity | Description |
|----|------|----------|-------------|
| AP36 | Golden Hammer | MEDIUM | Same solution for every problem |
| AP37 | Reinvent the Wheel | MEDIUM | Custom implementation of stdlib functionality |
| AP38 | Boat Anchor | LOW | Unused code kept "just in case" |
| AP40 | Base Bean | LOW | Inheriting for method reuse |
| AP48 | Dependency Hell | HIGH | Conflicting or redundant dependencies |

---

## Examples

### Python Examples

#### SRP Violation — Fat Controller

```python
# BAD: Handles validation, DB, caching, and notifications
class OrderController:
    def handle(self, request):
        if not self._validate(request.data):   # validation concern
            return error()
        order = self._save_to_db(request.data)  # persistence concern
        self._update_cache(order.id, order)     # caching concern
        self._send_notification(order)          # notification concern
        return success(order)

    def _validate(self, data): ...
    def _save_to_db(self, data): ...
    def _update_cache(self, id, obj): ...
    def _send_notification(self, order): ...
```

```python
# GOOD: Each class has one responsibility
class OrderValidator:
    def validate(self, data) -> bool: ...

class OrderRepository:
    def save(self, data) -> Order: ...

class CacheUpdater:
    def update(self, order_id: int, order: Order) -> None: ...

class OrderController:
    def __init__(self, validator: OrderValidator, repo: OrderRepository):
        self.validator = validator
        self.repo = repo

    def handle(self, request):
        if not self.validator.validate(request.data):
            return error()
        return success(self.repo.save(request.data))
```

#### DIP Violation — Direct Concrete Dependency

```python
# BAD: Depends on concrete implementation
class NotificationService:
    def __init__(self):
        self.mailer = SendGridMailer()  # Direct concrete dependency

    def send(self, msg):
        self.mailer.send(msg)
```

```python
# GOOD: Depends on abstraction
from abc import ABC, abstractmethod

class Notifier(ABC):
    @abstractmethod
    def send(self, msg: str) -> None: ...

class NotificationService:
    def __init__(self, notifier: Notifier):
        self.notifier = notifier

    def send(self, msg):
        self.notifier.send(msg)
```

#### Test Duplication — AP43

```python
# BAD: Same mock setup in every test
def test_create():
    mock_repo = MagicMock()
    mock_repo.save.return_value = Order(id=1)
    svc = OrderService(mock_repo)
    assert svc.create({"name": "x"})

def test_update():
    mock_repo = MagicMock()
    mock_repo.save.return_value = Order(id=1)
    svc = OrderService(mock_repo)
    assert svc.update(1, {"name": "y"})  # duplicated setup
```

```python
# GOOD: Use pytest fixture
@pytest.fixture
def order_repo():
    mock = MagicMock()
    mock.save.return_value = Order(id=1)
    return mock

@pytest.fixture
def order_service(order_repo):
    return OrderService(order_repo)

def test_create(order_service):
    assert order_service.create({"name": "x"})

def test_update(order_service):
    assert order_service.update(1, {"name": "y"})
```

### PHP Examples

#### SRP Violation — Fat Controller

```php
// BAD: Handles validation, DB, caching, and notifications
class OrderController {
    public function handle(Request $request): Response {
        if (!$this->validate($request->getData())) {     // validation
            return $this->error();
        }
        $order = $this->repo->save($request->getData());  // persistence
        $this->cache->update($order->getId(), $order);    // caching
        $this->mailer->send($order);                      // notification
        return $this->success($order);
    }
}

// GOOD: Each class has one responsibility
class OrderController {
    public function __construct(
        private OrderValidator $validator,
        private OrderRepository $repo,
    ) {}

    public function handle(Request $request): Response {
        if (!$this->validator->validate($request->getData())) {
            return $this->error();
        }
        return $this->success($this->repo->save($request->getData()));
    }
}
```

#### OCP Violation — If-Chain Dispatch

```php
// BAD: New format requires modifying existing code
class ReportGenerator {
    public function generate(array $data, string $format): string {
        if ($format === 'csv') { /* ... */ }
        elseif ($format === 'json') { /* ... */ }
        elseif ($format === 'pdf') { /* ... */ }
        // New format = edit this method
        return '';
    }
}

// GOOD: Open for extension
interface ReportRenderer {
    public function render(array $data): string;
    public function format(): string;
}

class CsvRenderer implements ReportRenderer {
    public function render(array $data): string { /* ... */ }
    public function format(): string { return 'csv'; }
}

class ReportGenerator {
    private array $renderers;

    public function __construct(iterable $renderers) {
        $this->renderers = $renderers;
    }

    public function generate(array $data, string $format): string {
        foreach ($this->renderers as $r) {
            if ($r->format() === $format) {
                return $r->render($data);
            }
        }
        throw new FormatNotFound($format);
    }
}
```

#### ISP Violation — Fat Interface

```php
// BAD: Service forced to implement unused methods
interface Processor {
    public function process(array $data): void;
    public function render(array $data): string;
    public function export(array $data, string $path): void;
}

class CsvProcessor implements Processor {
    public function process(array $data): void { /* ... */ }
    public function render(array $data): string { throw new BadMethodCallException(); }
    public function export(array $data, string $path): void { throw new BadMethodCallException(); }
}

// GOOD: Small focused interfaces
interface DataProcessor {
    public function process(array $data): void;
}

interface DataRenderer {
    public function render(array $data): string;
}

interface DataExporter {
    public function export(array $data, string $path): void;
}

class CsvProcessor implements DataProcessor, DataExporter {
    public function process(array $data): void { /* ... */ }
    public function export(array $data, string $path): void { /* ... */ }
    // render() not implemented = not forced to stub it
}
```

#### Test Duplication — AP43

```php
// BAD: Same factory setup in every test
class OrderControllerTest extends TestCase {
    public function testCreate(): void {
        $repo = $this->createMock(OrderRepository::class);
        $repo->method('save')->willReturn(new Order(1));
        $svc = new OrderService($repo);
        $this->assertTrue($svc->create(['name' => 'x']) !== null);
    }

    public function testUpdate(): void {
        $repo = $this->createMock(OrderRepository::class);  // duplicated
        $repo->method('save')->willReturn(new Order(1));     // duplicated
        $svc = new OrderService($repo);
        $this->assertTrue($svc->update(1, ['name' => 'y']) !== null);
    }
}

// GOOD: Use setUp() fixture
class OrderControllerTest extends TestCase {
    private OrderService $svc;

    protected function setUp(): void {
        $repo = $this->createMock(OrderRepository::class);
        $repo->method('save')->willReturn(new Order(1));
        $this->svc = new OrderService($repo);
    }

    public function testCreate(): void {
        $this->assertTrue($this->svc->create(['name' => 'x']) !== null);
    }

    public function testUpdate(): void {
        $this->assertTrue($this->svc->update(1, ['name' => 'y']) !== null);
    }
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
      "id": "AP14",
      "name": "Divergent Change",
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

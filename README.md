# blackroad-freedom-of-info

FOIA (Freedom of Information Act) request management system.

## Features
- Submit FOIA requests with unique tracking numbers
- Assign requests to processing officers
- Fulfill requests with document packages and redaction tracking
- Deny requests with exemption citations
- Appeal denied requests with grounds
- Automated overdue detection (20-day response window)
- Internal notes system for officer communication
- Agency-level statistics and reporting

## FOIA Exemptions
Standard FOIA exemptions (1-9) can be cited during denial.

## Usage
```bash
python foia_manager.py list
python foia_manager.py stats
python foia_manager.py overdue
python foia_manager.py report <request_id>
```

## Run Tests
```bash
pip install pytest
pytest tests/ -v
```

# ledgerdesk

Approval rules for supplier invoices: who may approve which invoice, and when.

- `ledgerdesk/policy/engine.py` decides; it starts from roles (`policy/roles.py`),
  delegations (`policy/delegation.py`) and the enabled plugins (`plugins/`).
- Configuration lives in `config/` and is layered per environment; see
  `ledgerdesk/config/loader.py`. Production runs with `LEDGERDESK_ENV=prod`.
- The data the engine reads (directory, invoices, rates, delegations, absences) is in
  `data/`. In production the same files are synced from the HR and ERP systems nightly.

```
python -m ledgerdesk invoices
python -m ledgerdesk who-can INV-2291 --explain
python -m ledgerdesk check mkoch INV-2291
```

Run the tests with `python -m pytest`.

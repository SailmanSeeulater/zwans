# strata

Loader for Strata, the configuration format our services use. The format is defined in
[SPEC.md](SPEC.md).

```python
import strata

config = strata.load("config/service.st")
config["server"]["port"]  # 8080
```

`config/` holds the configuration of the ingest service, which is the first user of the
loader. Run the tests with `python -m pytest`.

# todo

A tiny command-line todo list. Tasks are kept in a JSON file (`todo.json` in the
current folder, or the path given with `--file`).

```
python -m todo add "Buy milk"
python -m todo done 1
python -m todo list [--pending]
```

Run the tests with `python -m pytest`.

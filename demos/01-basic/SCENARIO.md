# Demo 01 - basic: ship, A/B, and roll back a support-bot prompt

This walkthrough exercises the full PROMPTPACK lifecycle on a realistic
customer-support summarization prompt. All commands are stdlib-only and write
to a local JSON registry (`--db`), so nothing touches the network.

We use an isolated registry file so the demo is repeatable:

```sh
export PROMPTPACK_DB=./demo.json
rm -f ./demo.json
```

## 1. Commit v1 from the seed file

```sh
python -m promptpack commit support.summarize --file demos/01-basic/support_summarize.txt -m "initial"
```

## 2. Iterate: commit a tweaked v2 inline

```sh
python -m promptpack commit support.summarize \
  --body 'You are a concise support agent. Summarize the ticket from {customer} about "{subject}" in <= {max_words} words, then suggest one next action.' \
  -m "add next-action ask"
```

## 3. Promote v2 to a `prod` tag

```sh
python -m promptpack tag support.summarize prod --ref 2
```

## 4. Render `prod` with real variables

```sh
python -m promptpack render support.summarize --ref prod \
  --var customer=Acme --var subject="billing error" --var max_words=40
```

## 5. Run a weighted A/B between v1 (20%) and v2 (80%)

```sh
python -m promptpack ab support.summarize prod 1:1 2:4
# deterministic bucketing per user id:
python -m promptpack choose support.summarize prod --key user-12345 --format json
```

## 6. v2 misbehaves in prod -> roll back to v1

```sh
python -m promptpack rollback support.summarize prod 1 --format json
python -m promptpack diff support.summarize 1 2
```

Expected: `rollback` reports `{"from": 2, "to": 1}` and the tag now resolves to v1.

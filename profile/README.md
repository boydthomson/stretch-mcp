# stretch-ops profile

The Hermes agent profile that uses this server. It runs on a local model and lives in one
private Matrix room.

- `SOUL.md`: who the agent is, where facts come from, what counts as needing attention,
  and the rules for proposing changes.
- `config.snippet.yaml`: the MCP server entry and the reduced toolsets.
- `morning-brief.txt`: the prompt for the scheduled morning brief.

Install on a Hermes host:

```bash
hermes profile create stretch-ops --clone-from <an existing profile> --no-alias
cp SOUL.md ~/.hermes/profiles/stretch-ops/SOUL.md
# merge config.snippet.yaml into ~/.hermes/profiles/stretch-ops/config.yaml
hermes -p stretch-ops cron create "0 6 * * *" "$(cat morning-brief.txt)" \
  --name morning-brief --deliver matrix --timezone America/Vancouver
```

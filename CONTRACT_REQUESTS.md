# Contract requests

The one shared file of the parallel build. An agent that needs a change outside its own files appends an entry here
(one shell append, never an edit of existing text), lists it in its final report and keeps going with a local adapter.
The integrator decides each entry and notes the decision under it; only the integrator edits existing text.

Entry format:

```text
### <agent> · <file> · <short title>
- Change: <the exact change>
- Why: <the reason, with the docs/SPEC.md, docs/BRAIN_API.md or docs/UI_SPEC.md section it follows>
- Local adapter: <what the agent does meanwhile>
- Decision: <left empty; the integrator writes accepted or rejected, with a note>
```

## Entries

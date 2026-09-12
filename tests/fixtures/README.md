# tests/fixtures

Small JSON/YAML/Python inputs pin payload shape for unit/integration consumers;
this directory owns fixture bytes, not execution.

Follow each consuming family map; there is no standalone pytest route. See the
[tests index](../README.md). Historical pseudo-data is documented separately.

The preserved trees are `generated_capabilities/` (stub model/loss imports),
`health/` (blocking/observe-only YAML), `robs1/` (observable plugins), and
`step10_p1/` (historical task-composition fixtures). Their consuming tests
own interpretation; fixture bytes are retained as evidence, not shipped task
support.

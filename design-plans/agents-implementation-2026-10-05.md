# Saved agents and automations

Implemented in Chisel: persisted goals, installed-model selection, a first-run time, once/hourly/daily/weekly schedules, status indicators, pause/resume, fresh reruns, deletion, and inspectable progress/run history.

Runs require Uncloud's local sidecar to remain running. Closing the app does not install a system daemon. Interrupted runs pause for attention on restart. Missed intervals produce one due run, never a backlog burst. Tasks run serially and cannot switch an actively selected different model or interrupt an active chat. Normal chat cannot switch/unload a model reserved by a background run; pause the saved agent first.

Agents reuse the existing local planner and execution engine. No idle inference. Goals/results are encrypted with the existing vault key; disk file permissions are owner-only. History retains the latest 20 runs. Resume supplies retained progress to replanning; it is not an exact instruction-pointer continuation or an exactly-once guarantee. Use Run fresh for an independent rerun.

Background tools are limited to selected workspace read/research capabilities. Files remain confined to the Uncloud workspace even if interactive full-device access is enabled. Background runs never inherit session grants or interactive approval prompts. Current global Read/Network policies still apply: Ask/Deny pauses the run, rather than silently granting access. Computer control, shell, writes, generation, and integrations remain available in interactive Chisel, outside this unattended scope. The planner receives only the scoped tool descriptions, and execution checks scope again.

Validation: full local backend regression suite, frontend tests/build, targeted scheduler/API/permission tests, and isolated read-only browser layout review. Scheduler tests use deterministic fake executors: they do not establish real-model task quality or Windows/Linux native capture behavior. No real user automation was created or run. This is source implementation, not a newly published installer.

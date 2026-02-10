# Ideas

## Refresh groups button

Add a manual "Uppdatera" button in the groups tab that re-fetches group data
from signal-cli via `log_groups()` and updates `app_state.groups`. This way
newly joined groups appear in the web GUI without restarting Oden.

The startup task `log_groups` already does this on boot — the new endpoint
would reuse that function. The handler needs access to `reader`/`writer` from
`app_state`, and should return a clear error if signal-cli isn't connected.

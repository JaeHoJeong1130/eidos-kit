# Eidos v3

New Work IDs include the initial member key and 12 random hex characters. Generated filenames
are at most 80 ASCII characters; only the slug is shortened, while the full document title remains.
Existing Work filenames and references are preserved. Current ownership is `owner_id`, even
after reassignment. See `.agents/workflows/eidos-v3.md` for creation and compatibility rules.

Direction records stable strategy. Work records durable, independently owned execution. Run
`.agents/tools/eidos.py focus --summary` for the derived current view; do not add a manual Current Focus
section. Agent claims are local leases stored under the Git common directory and never constitute
shared project truth. `identity.json` is the project-owned human identity registry: new Work must
use an active canonical `member:*` ID, while aliases preserve historical ownership without rewriting
closed Work. An unconfigured registry keeps legacy records readable but blocks new Work creation.

The six Direction sections have a fixed order and occur exactly once. Use claim list or kit doctor
to surface malformed claims, scope drift, and orphaned dirty paths; never delete claim history to
hide a finding. Every actual Work has one explicit human owner. A claim separately records the
canonical human member and the acting `agent:*` identity. Claim worktree references use
opaque, non-reusable instance identities, so a recreated worktree cannot inherit historical claim
state. Adoption preserves the immutable origin and all prior worktree custodians. Unavailable
local state remains unknown; read-only focus and claim-list operations do not refresh the Git
index. Scope aliases use repository case semantics and canonical separators/dot segments;
trailing-dot/space components and Git pathspec syntax are rejected before literal Git probes.

Use `work start --input <file|->` and `work finish --input <file|->` to create/close Work together
with its claim. JSON examples and recovery rules are in `.agents/workflows/eidos-v3.md`.
R1 Work may be concise. New commands require actual purpose, completion criteria, verification,
result and evidence; they never execute checks or certify submitted evidence. Older placeholder
content warns. Open v3 Work may finish against an archived Direction; new Work uses the current one.

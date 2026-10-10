# Contributing

Device packages, userspace integration, build tools and documentation belong in
this repository. Drivers, device trees and kernel configuration belong in the
separate device-kernel repository. The selected revision is recorded in
[kernel/source.json](kernel/source.json). Kernel changes belong in
[linux-sm8750-erhai](https://github.com/yzddmr6/linux-sm8750-erhai).

Keep changes focused and explain the problem, resulting behavior and validation.
Preserve original authorship and licenses when adapting community code. Prefer
existing Linux subsystems and distribution packages over device-specific services.

Run checks relevant to the change. Documentation-only changes need link and
consistency checks, not a kernel rebuild. For device results, report the model,
firmware, exact software version, reproduction steps and observed outcome.
Distinguish compilation, emulation and hardware tests; do not infer functionality
from a device node or a successful probe alone.

Remove credentials, serial numbers, wireless addresses and personal data from
shared logs. Do not include factory calibration or private keys in contributions.
The README lists the project's discussion channels.

Keep published version tags immutable. A binary release must identify matching
sources and inputs, its supported installation scope and known limitations.
Kernel upstream submissions follow the target subsystem's contribution rules;
publishing this project's development source is a separate step.

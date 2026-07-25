# Generated import blocks so `tofu plan` ADOPTS the rulesets that already exist
# instead of trying to create duplicates. Regenerate after any manual change:
#   python3 ../scripts/gen-imports.py > imports.tf
#
# Verify with `tofu plan`: a correct adoption shows "0 to add, 0 to destroy".
# Anything else means the code and the live state disagree — investigate before
# applying, do not just accept the diff.

import {
  to = github_repository_ruleset.component_dev["mycelium-bench"]
  id = "mycelium-bench:19715173"
}

import {
  to = github_repository_ruleset.component_main["mycelium-bench"]
  id = "mycelium-bench:19592407"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-build"]
  id = "mycelium-build:19715174"
}

import {
  to = github_repository_ruleset.component_main["mycelium-build"]
  id = "mycelium-build:19592411"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-check"]
  id = "mycelium-check:19715175"
}

import {
  to = github_repository_ruleset.component_main["mycelium-check"]
  id = "mycelium-check:19592414"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-cli"]
  id = "mycelium-cli:19715176"
}

import {
  to = github_repository_ruleset.component_main["mycelium-cli"]
  id = "mycelium-cli:19592415"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-cli-common"]
  id = "mycelium-cli-common:19715178"
}

import {
  to = github_repository_ruleset.component_main["mycelium-cli-common"]
  id = "mycelium-cli-common:19592417"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-codegen"]
  id = "mycelium-codegen:19715161"
}

import {
  to = github_repository_ruleset.component_main["mycelium-codegen"]
  id = "mycelium-codegen:19592419"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-core"]
  id = "mycelium-core:19715163"
}

import {
  to = github_repository_ruleset.component_main["mycelium-core"]
  id = "mycelium-core:19592422"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-doc"]
  id = "mycelium-doc:19715179"
}

import {
  to = github_repository_ruleset.component_main["mycelium-doc"]
  id = "mycelium-doc:19592425"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-fmt"]
  id = "mycelium-fmt:19715181"
}

import {
  to = github_repository_ruleset.component_main["mycelium-fmt"]
  id = "mycelium-fmt:19592426"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-l1"]
  id = "mycelium-l1:19715164"
}

import {
  to = github_repository_ruleset.component_main["mycelium-l1"]
  id = "mycelium-l1:19592428"
}

import {
  to = github_repository_ruleset.umbrella_dev
  id = "mycelium-lang:19715183"
}

import {
  to = github_repository_ruleset.umbrella_main
  id = "mycelium-lang:19592430"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-lint"]
  id = "mycelium-lint:19715189"
}

import {
  to = github_repository_ruleset.component_main["mycelium-lint"]
  id = "mycelium-lint:19592431"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-lsp"]
  id = "mycelium-lsp:19715190"
}

import {
  to = github_repository_ruleset.component_main["mycelium-lsp"]
  id = "mycelium-lsp:19592437"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-proj"]
  id = "mycelium-proj:19715191"
}

import {
  to = github_repository_ruleset.component_main["mycelium-proj"]
  id = "mycelium-proj:19592436"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-runtime"]
  id = "mycelium-runtime:19715166"
}

import {
  to = github_repository_ruleset.component_main["mycelium-runtime"]
  id = "mycelium-runtime:19592439"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-sec"]
  id = "mycelium-sec:19715193"
}

import {
  to = github_repository_ruleset.component_main["mycelium-sec"]
  id = "mycelium-sec:19592441"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-spore"]
  id = "mycelium-spore:19715194"
}

import {
  to = github_repository_ruleset.component_main["mycelium-spore"]
  id = "mycelium-spore:19592443"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-cmp"]
  id = "mycelium-std-cmp:19715195"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-cmp"]
  id = "mycelium-std-cmp:19592446"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-collections"]
  id = "mycelium-std-collections:19715196"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-collections"]
  id = "mycelium-std-collections:19592447"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-conformance"]
  id = "mycelium-std-conformance:19715198"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-conformance"]
  id = "mycelium-std-conformance:19592449"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-content"]
  id = "mycelium-std-content:19715199"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-content"]
  id = "mycelium-std-content:19592452"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-core"]
  id = "mycelium-std-core:19715167"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-core"]
  id = "mycelium-std-core:19592455"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-dense"]
  id = "mycelium-std-dense:19715200"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-dense"]
  id = "mycelium-std-dense:19592456"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-diag"]
  id = "mycelium-std-diag:19715201"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-diag"]
  id = "mycelium-std-diag:19592459"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-error"]
  id = "mycelium-std-error:19715202"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-error"]
  id = "mycelium-std-error:19592460"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-fmt"]
  id = "mycelium-std-fmt:19715203"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-fmt"]
  id = "mycelium-std-fmt:19592462"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-fs"]
  id = "mycelium-std-fs:19715204"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-fs"]
  id = "mycelium-std-fs:19592464"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-io"]
  id = "mycelium-std-io:19715147"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-io"]
  id = "mycelium-std-io:19592466"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-iter"]
  id = "mycelium-std-iter:19715205"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-iter"]
  id = "mycelium-std-iter:19592468"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-math"]
  id = "mycelium-std-math:19715206"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-math"]
  id = "mycelium-std-math:19592470"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-numerics"]
  id = "mycelium-std-numerics:19715208"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-numerics"]
  id = "mycelium-std-numerics:19592472"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-rand"]
  id = "mycelium-std-rand:19715210"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-rand"]
  id = "mycelium-std-rand:19592474"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-recover"]
  id = "mycelium-std-recover:19715211"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-recover"]
  id = "mycelium-std-recover:19592476"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-runtime"]
  id = "mycelium-std-runtime:19715212"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-runtime"]
  id = "mycelium-std-runtime:19592478"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-select"]
  id = "mycelium-std-select:19715213"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-select"]
  id = "mycelium-std-select:19592481"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-spore"]
  id = "mycelium-std-spore:19715214"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-spore"]
  id = "mycelium-std-spore:19592484"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-swap"]
  id = "mycelium-std-swap:19715215"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-swap"]
  id = "mycelium-std-swap:19592485"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-sys"]
  id = "mycelium-std-sys:19715216"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-sys"]
  id = "mycelium-std-sys:19592488"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-sys-host"]
  id = "mycelium-std-sys-host:19715217"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-sys-host"]
  id = "mycelium-std-sys-host:19592487"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-ternary"]
  id = "mycelium-std-ternary:19715219"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-ternary"]
  id = "mycelium-std-ternary:19592491"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-testing"]
  id = "mycelium-std-testing:19715221"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-testing"]
  id = "mycelium-std-testing:19592494"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-text"]
  id = "mycelium-std-text:19715222"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-text"]
  id = "mycelium-std-text:19592496"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-time"]
  id = "mycelium-std-time:19715225"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-time"]
  id = "mycelium-std-time:19592498"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-std-vsa"]
  id = "mycelium-std-vsa:19715227"
}

import {
  to = github_repository_ruleset.component_main["mycelium-std-vsa"]
  id = "mycelium-std-vsa:19592500"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-transpile"]
  id = "mycelium-transpile:19715228"
}

import {
  to = github_repository_ruleset.component_main["mycelium-transpile"]
  id = "mycelium-transpile:19592501"
}

import {
  to = github_repository_ruleset.component_dev["mycelium-value"]
  id = "mycelium-value:19715169"
}

import {
  to = github_repository_ruleset.component_main["mycelium-value"]
  id = "mycelium-value:19592504"
}


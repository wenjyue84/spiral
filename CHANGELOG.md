# Changelog

All notable changes to SPIRAL are documented in this file.
Commits follow the [Conventional Commits](https://www.conventionalcommits.org/) specification.
Generated automatically by [git-cliff](https://git-cliff.org/).

## [Unreleased]

### Bug Fixes

- Add UTF-8 stdout guard to all Python scripts ([4c1fd2f](4c1fd2f82f6132e41d7ec0143c4244d8c3981005))


### Documentation

- Add Chrome DevTools MCP + agent-browser to prerequisites ([c2748a6](c2748a685ec3b1ac375efdd17a7486dd7056d2d7))

- Add setup wizard + spiral-init to README ([6f0226e](6f0226e1962123ea4bf69c2a4c46f961a9e79268))

- Document US-140 learnings in progress.txt ([d45a1f3](d45a1f38d853fe5cecdab71166a05d67854486bc))


### Features

- Initial extraction of SPIRAL from prisma-erp ([b60cd63](b60cd63224ef4cfcfb037cabc98032e5db20f710))

- Bundle Ralph, add setup.sh, rewrite README ([49f6af3](49f6af3aa47f8c35607aed9c4492eae9fc9b54dc))

- Dynamic Claude model routing + Firecrawl MCP support ([aabe807](aabe8075c62bcde9cf7a2bafb60d06ec68fea3da))

- GitNexus semantic fallback for populate_hints.py ([2c4ffc8](2c4ffc89a6f974b09543531adf93918399296f93))

- Add story decomposition for failed stories ([1fa3787](1fa378724a2bf20fc1ee3e9428ac26fbcb72bb9a))

- Add focus theme + max-pending to merge pipeline ([60fa029](60fa0295571bd76f3a03a0f82b67cee65f14edb8))

- Add memory pressure management scripts ([ef83639](ef8363947071797136727989bade6d924af615be))

- Add SPIRAL session report generator ([385f2d5](385f2d526392cf9c7c5cef047f4868a532dd87ce))

- Add rules 8-12 to Ralph agent instructions ([d964a89](d964a89fdeb2024aeadc81be1630d0f0842ebe07))

- Add spiral-init skill + first-run detection ([1d2a313](1d2a31346248cc106e1dbc93ad4ea8add4dcbaf6))

- Decomposition, model routing, memory mgmt, focus in ralph ([203d216](203d216f6747dcbb05e5f1d80e2a28cbae2ad7af))

- Adaptive wait, cleanup, worker isolation in parallel runner ([e9f733e](e9f733ec44cc1bce132f887a4062b72304622e46))

- Focus, memory mgmt, spec-kit, cleanup in spiral loop ([24a87fb](24a87fb030b813c6454f4602843a6a916e97724d))

- Add focus, time budget, spec-kit config examples ([f51bdd3](f51bdd3bb00d9fb58450c9792ee5283d1d4b5bb4))

- Add periodic status report to ralph (default every 30m) ([1889f3a](1889f3a9fccba0c88d9c62ac082a2ab664957d0d))

- Add HTML metrics dashboard with auto-open after every iteration ([bd2f1fe](bd2f1feffff8231bc3e729691e5e0cc65f4a7dfb))

- Mark US-001 complete — validate_preflight.sh already wired into spiral.sh ([3576723](3576723cf89c65f9f1c2c4e77c17e2911ce53d93))

- US-001 - Wire validate_preflight.sh into spiral.sh startup ([d686320](d686320ea8b923563f38a432f32d3c56515d6eba))

- US-002 - Run DAG cycle detection before Phase I implementation ([fa7ba5a](fa7ba5a24d8775213283fead4e89465bea812ca9))

- US-002 - Run DAG cycle detection before Phase I implementation ([83d6662](83d666260db5b1d2a4ed550cc029d5cd5d79d6d4))

- US-005 - Wizard: ask about model routing strategy with cost/quality education ([128f9b1](128f9b191acf8eb1a483a77501fa16ecf038f544))

- US-005 - Wizard: ask about model routing strategy with cost/quality education ([1c1c7c2](1c1c7c21c72c5295b7999d21321bac5ff964eafc))

- US-006 - Wizard: ask about research phase configuration (Gemini, Firecrawl, capacity limit) ([10730f7](10730f788a02f2e992604142dc6459feda24deaf))

- US-006 - Wizard: ask about research phase configuration (Gemini, Firecrawl, capacity limit) ([15f595d](15f595d96be3de5511defb3ce1af89d181957990))

- US-011 - ralph.sh reads per-story .model field from prd.json at runtime ([4d64bae](4d64baefcb651c3c5362c260adfc1dc91cd2e0cd))

- US-011 - ralph.sh: read per-story model field from prd.json at runtime ([be4eda3](be4eda316ae8296221e705ad024b51a39c582474))

- US-012 - Emit results.tsv telemetry row per story attempt in ralph.sh ([e87282d](e87282d09703036f74b5485c1ea79a9fa9769eb9))

- US-012 - Emit results.tsv telemetry row per story attempt in ralph.sh ([0846b62](0846b62cb5ee63c7b21249676919105257c91d11))

- US-013 - Add unit tests for route_stories.py ([1ced12b](1ced12b6d4931fba7d435450d5833ffc372e4131))

- US-013 - Add unit tests for route_stories.py (annotation, profile propagation, atomic write) ([37184a1](37184a1e6f07e86747a3a6b6054745328dde9593))

- US-014 - Mark stories _skipped: true when MAX_RETRIES is exhausted ([6c07987](6c079875e2e4049139b2a776e14a4ff71823f883))

- US-014 - Mark stories _skipped: true when MAX_RETRIES is exhausted to stop infinite retries ([bbb2ca0](bbb2ca07b87c9ddefbd1f43563447cbb205dbf00))

- **spiral**: Complete 8 stories (iter 1) ([ff1346f](ff1346fa461dcafc34eedb51bd005f335358dac5))

- US-003 - Validate checkpoint state machine coherence at startup ([9977a78](9977a78ac15b8a3dadcd9eaafa75c2df99467785))

- US-026 - Add unit tests for check_done.py (PRD gate + report logic) ([64212ca](64212caf631a15bc124e8a8501b605c83a350deb))

- US-026 - Add unit tests for check_done.py (PRD gate + report logic) ([abc6fe7](abc6fe7ab5bbde72143d6ba30a571e9cdd3517c5))

- US-027 - Add unit tests for decompose_story.py (ID allocation + JSON extraction) ([c3d5656](c3d56566c191dc4752703248b17246b2b6cabbc8))

- US-027 - Add unit tests for decompose_story.py (ID allocation + JSON extraction) ([4423b15](4423b155fab058999fc1598ff1a7d226cf9d6d45))

- US-028 - Auto-create timestamped prd.json backup before Phase M merge ([322dc7a](322dc7a518e86cd4f12876d6e902e8c81961f2c6))

- US-028 - Auto-create timestamped prd.json backup before Phase M merge ([db33e9f](db33e9f3c6af81073d273b4a0eb8585f00e7c42f))

- US-004 - Gate report only in interactive mode (skip in --gate proceed) ([ffa6bc5](ffa6bc5e2499415ccc68434a232a654ecf406d7a))

- US-029 - Replace heuristic call_claude() with real Claude CLI subprocess ([ea443c5](ea443c5136b93476eda83becc2956e74be8c0258))

- US-029 - Implement real Claude API call in route_stories.py auto mode ([fc3a697](fc3a697d26d99536cab72ea13d7d149428f258b7))

- US-007 - Add Browser Testing wizard section to spiral-init.md ([8d2ef88](8d2ef88fecc10d640e5f58fc4b01e3f6c3f7e4e3))

- US-040 - Add prd.json write lock to prevent parallel worker corruption ([263a137](263a137575e14da3ccd11bb298dfbf66ce54f71e))

- US-040 - Add prd.json write lock to prevent parallel worker corruption ([839dc93](839dc93954d5cd3e1b42b0cc3c7bf4afe8aee020))

- US-041 - Enforce dependency-order execution: skip story if deps not yet passed ([9b7e066](9b7e0667b32e66390df87241892ba2b96a77a13c))

- US-041 - Enforce dependency-order execution: skip story if deps not yet passed ([94166c9](94166c914cb6a9c2b52e92cfb60757a3bf2b921b))

- US-059 - Add disk space preflight check before creating N git worktrees ([5bb8bd9](5bb8bd9fb882c6dbb42c20faa9b0527534d1e13d))

- **spiral**: Complete 10 stories (iter 1) ([c64b24e](c64b24ee3f4b65343e2e0d73a19eb88634bcbe7b))

- US-042 - Add SPIRAL_STORY_BATCH_SIZE to cap stories visible to ralph per iteration ([c8319e9](c8319e981af5d0ddf71cda73be49a8ce955d52d9))

- US-042 - Add SPIRAL_STORY_BATCH_SIZE to cap stories visible to ralph per iteration ([0538fcf](0538fcf0947298bb1aead5a3462b9e4c73d07ae7))

- US-058 - Merge parallel worker results.tsv files into main results.tsv ([4331502](43315022973ad35368dc06e6e052bed6ece45d01))

- US-043 - Add SPIRAL_COST_CEILING to abort when cumulative API spend exceeds budget ([e9fa199](e9fa1997a026c2eaedbc60985189bbe85467c06a))

- US-043 - Add SPIRAL_COST_CEILING to abort when cumulative API spend exceeds budget ([0b98ff2](0b98ff27d1e8dc6ccd10f0cfdc0f07adb9a91a07))

- US-060 - Add unit tests for merge_worker_results.py (parallel result promotion) ([2f0c30f](2f0c30fd5ece4d2a8784040e7a1dd79600c9f67d))

- US-060 - Add unit tests for merge_worker_results.py (parallel result promotion) ([a213169](a2131698a7287e52c11d748d171399a749afa9cc))

- US-015 - Add GitHub Actions CI workflow to run pytest on every push and PR ([85ddf46](85ddf46c79534695269e84c40b799a7325df029c))

- US-018 - Validate required spiral.config.sh keys before loop startup ([d9a79e5](d9a79e51d8fd359c37c3b583081aad05f7632c85))

- US-009 - Dynamic worker count based on story independence ratio ([2335d33](2335d3382a264438a793eac31326933cc35b6086))

- US-009 - Dynamic worker count: auto-select 1-3 workers based on story independence ([c6229e9](c6229e910dba1f65f86101ff7a5e383a080fbbf3))

- US-016 - Add unit tests for populate_hints.py (keyword extraction and filesTouch mutation) ([a14b58d](a14b58d789b8f3c8ef12cc1f8cf3b7694a717d2e))

- **spiral**: Complete 8 stories (iter 2) ([f1602d2](f1602d2a075ca8da814162cf1d5b6996b4e5273a))

- US-008 - Wizard advanced lifecycle tuning (retries, GitNexus, deploy hook) ([ef5e6f8](ef5e6f8a3883e659f05f056af9179552dc7fabdd))

- US-010 - Chrome DevTools Phase V screenshot after validation ([bccb641](bccb6414f39badc05dd75e652b997de4334a4cd3))

- US-010 - Chrome DevTools Phase V: screenshot running app after validation ([6e9a7f6](6e9a7f696b48a1297fa387cd26986129bae0a245))

- US-017 - Add SIGINT/SIGTERM trap to spiral.sh for graceful shutdown and checkpoint flush ([c6bf65d](c6bf65d9728eae4428858262d2d759ca716725d7))

- US-019 - Move retry-count increment to ralph.sh for correctness ([6548a00](6548a0008907828152eccafe300b01840227a7e9))

- US-030 - Validate _research_output.json schema before Phase M merge ([d0fc52b](d0fc52bad04a5085d4d3644ad88e5bcb127c291c))

- US-031 - Detect duplicate story IDs in validate_prd and reject them ([1594c9a](1594c9aa4ea94286c5470f8b60a207cbbc906b3b))

- **spiral**: Complete 6 stories (iter 4) ([112aa92](112aa92f3b91b042fd82cbfd417b2a8d0c8e4834))

- US-020 - Implement main.py as proper CLI with init, run, status subcommands ([5c25b93](5c25b930435b1a975f042f2dfa60557032ea0932))

- US-021 - Add estimated token cost card to spiral_dashboard.py overview ([d07f474](d07f474dd36af2a47b2a7acbd8394b000548fd23))

- US-076 - Add SIGCHLD trap to reap zombie worker processes ([da7db67](da7db670dafe4d2353b11174cf906ab2c13e2873))

- US-076 - Add SIGCHLD trap to spiral.sh to reap zombie worker processes ([3db673b](3db673b6bc26cd597d024e05fa33b749c553af6e))

- US-077 - Lock git worktrees to prevent prune races during worker execution ([7b77d36](7b77d36805a66d7ca148180af53e9d69b2264556))

- US-077 - Lock git worktrees during active worker execution to prevent prune races ([15644f2](15644f24a35ad114268d374cda1131ff5f8d3f00))

- US-078 - Guard against 'branch already checked out' before git worktree add ([9ec3a1b](9ec3a1bc88d8f90ee9fa44ad7927ca364d8d3496))

- US-078 - Guard against 'branch already checked out' before git worktree add ([dae05bd](dae05bd9553baa28d53a017293b4de488debd321))

- US-079 - Handle HTTP 529 overloaded_error with separate backoff strategy ([3920deb](3920deb4be623e512ee22067c3a753d9407f4b58))

- US-079 - Handle HTTP 529 overloaded_error with separate backoff strategy from 429 ([ceefd3b](ceefd3b08e4c597a972868faddd2d89f42fcc07c))

- US-032 - Add --status flag to spiral.sh for quick session inspection ([8cc0189](8cc018978349f4996e191a14536c4a5e18e13c16))

- US-033 - Detect API 429 rate-limit in ralph.sh and pause without burning a retry ([43cb180](43cb180afc6226d79d375224d81f44e4fbb5fd4b))

- US-035 - Add SPIRAL_MAX_RESEARCH_STORIES cap in Phase M merge ([164fcd7](164fcd70dfdb67fba08adbb807f8a8b0986d24cf))

- **spiral**: Complete 9 stories (iter 5) ([36e12bc](36e12bcb88d332afa663fc5609b2002afd63382e))

- **dashboard**: Add per-iteration story velocity bar chart (US-034) ([797d0e4](797d0e40ad1e4e9b10f301a130ead8301d9194bf))

- **spiral**: Add --dry-run flag to test loop control flow without API calls (US-022) ([18e4ec6](18e4ec66908ae4b16b3449f7b83cc21f9bc44605))

- US-022 - Add --dry-run flag to spiral.sh to test loop control flow without API calls ([0c4a273](0c4a273a5317e4792485bfda04fce88dc2243a99))

- US-036 - Add spiral-doctor command to verify all runtime dependencies ([deb3a58](deb3a580f358bbd8c38350a094318b26668363d2))

- US-037 - Rotate progress.txt when it exceeds SPIRAL_PROGRESS_MAX_LINES ([ba9d45f](ba9d45f8dd20349a76f2b73b8cae53012e246605))

- US-023 - Auto-generate progress.txt skeleton with Codebase Patterns on first run ([d782eea](d782eeafe51ff5eecd9fa042c092e67d2d6a40d6))

- US-023 - Auto-generate progress.txt skeleton with Codebase Patterns on first run ([6faab12](6faab128677ef85b34882c772c3cddc00b5c8678))

- US-044 - Write structured JSONL event log to .spiral/spiral_events.jsonl ([c3c7acd](c3c7acdbfc8942c2e9e0bf0da1726c5dd7e7b847))

- US-045 - Cache research HTTP responses in .spiral/research_cache/ with TTL ([a2b6573](a2b6573bd23e24de7cdb5487487dbfe9809bfd49))

- **spiral**: Complete 7 stories (iter 6) ([8a59374](8a593744a601a01d5e0c28a0fedb2b55c9c7832a))

- **US-095**: Add per-worker execution timeout via SPIRAL_WORKER_TIMEOUT ([672368d](672368df342cac19fc494e2b5f05d5f945a832bc))

- US-095 - Add per-worker execution timeout using `timeout --kill-after` in run_parallel_ralph.sh ([b0938c3](b0938c3b2648db4f7f53053fd3957a66ac520b88))

- US-096 - Add SPIRAL_VALIDATE_TIMEOUT to bound Phase V test-suite execution time ([dfa3247](dfa32479326cf19d936c6b699dbad7de59fe4a1c))

- US-096 - Add SPIRAL_VALIDATE_TIMEOUT to bound Phase V test-suite execution time ([b93f22a](b93f22ac415123e52722e80027b8668af7af60c6))

- US-097 - Detect git merge conflicts with merge-tree before parallel worker integration ([f5c6141](f5c6141c485173c5e32858c46e432fce703a2817))

- US-097 - Detect git merge conflicts with `git merge-tree` before parallel worker integration ([9b7dfdc](9b7dfdc729f1e6546538e3f8c90676af7433b3a9))

- US-098 - Add spiral.sh --replay STORY_ID to re-run single story without full loop ([a072050](a072050b05d2ce25c91764501ac84f106e3fe71d))

- US-098 - Add `spiral.sh --replay STORY_ID` to re-run a single story without full loop ([8642f1a](8642f1a4dae94cef80b33ffb0b66030c6f1b7069))

- **spiral**: Complete 4 stories (iter 7) ([bc63981](bc63981446ab7578f2d5ea3f75b96af07ed8103d))

- US-046 - Record phase start/end timestamps in _checkpoint.json ([bffcd03](bffcd03c1ec9fa7f833e0bec25ce0d03f394eab5))

- US-047 - Record _passedCommit git SHA in prd.json when story passes ([30d2c1d](30d2c1d6e019f5a89753ef3dd07f9e2ccaa37cd0))

- **spiral**: Complete 2 stories (iter 8) ([55b8d81](55b8d817108d834417f6c70baf08255b01a3d0e3))

- US-025 - Dashboard progress.txt activity feed with collapsible section ([40d1a8b](40d1a8b114542a28f9c7bd1c4e6d39fa1f2c6807))

- US-048 - Mark epicId grouping field story as complete ([aa0daaf](aa0daaf21d73de02521a27896f995c5bb8a3eb7d))

- US-049 - Add SPIRAL_ON_COMPLETE hook for post-completion automation ([e047d32](e047d320595c72a385e9868058a4f9effb034981))

- US-050 - Add unit tests for synthesize_tests.py (report parsing and priority mapping) ([53529cf](53529cff77cdb0289b021ab2a15918d62e00286e))

- US-051 - Add unit tests for merge_stories.py (deduplication and atomic prd.json patch) ([ab472bc](ab472bc260c86a82f39987f3c0c8cf04db642840))

- US-024 - Add TLA+ ModelAssignmentConsistent invariant to SpiralWorkers.tla ([10a58d5](10a58d5bd75ef3aa496eae5d9fb7a087bc63a1be))

- US-024 - Add TLA+ ModelAssignmentConsistent invariant to SpiralWorkers.tla ([0588ec1](0588ec1a0be34d5cf18645f3609f28e1d1895ba2))

- US-052 - Add unit tests for state_machine.py (StoryLifecycle and phase transitions) ([0dbc502](0dbc5025443ea3b9d32ee891cf8095d3f460dca2))

- US-038 - Warn when resuming from checkpoint older than 24 hours ([302c051](302c051fe087d899ba716c45ca6c44bae8aa38c6))

- US-038 - Warn when resuming from a checkpoint older than 24 hours ([20ab506](20ab506a71223068a677b71022208aa72c86819c))

- **spiral**: Complete 8 stories (iter 9) ([b1032a3](b1032a306bc13cb6b359f42d461a794d69a96811))

- **spiral**: US-108 - Add circuit breaker for LLM API calls ([d789931](d789931ed9d90fcccf33dd354500a03b53f43946))

- US-108 - Add circuit breaker for LLM API calls with half-open recovery ([f556f64](f556f6463eab52c83a0b1d10063a86775019453d))

- US-053 - Implement worker heartbeat stale detection and auto-requeue ([38a9bc6](38a9bc62677d14744971034dc4ab0d9e15ddae50))

- US-110 - Add prd.json JSON Schema file and validation as CI preflight gate ([ebe6560](ebe6560cd24e9419bb01c1c9117d7dabce63b81b))

- US-109 - Add per-phase timeout with two-phase kill to all LLM invocations ([739587b](739587b5e020d76fd7300fdc920179fb34d84ce2))

- US-109 - Add per-phase timeout with two-phase kill to all LLM invocations ([27f33c5](27f33c5c444524cf0b59a25f734e146be1416558))

- US-111 - Add per-story token cost accumulation and soft/hard budget enforcement ([cd02d4f](cd02d4f4eb425b105a3435493dd64be29d95e44e))

- US-111 - Add per-story token cost accumulation and soft/hard budget enforcement ([451c03c](451c03c5db49b30638e8e250d71aae07ac558ffe))

- US-054 - Add schemaVersion field to prd.json with auto-migration on load ([0647706](0647706443402a5d9f57b0c71f9c2af526a8580b))

- **spiral**: Complete 6 stories (iter 10) ([c5a460c](c5a460c29e8ef13cedb961711833e06d55a7b320))

- US-112 - Add model fallback chain with per-model circuit breaker state ([4a52e51](4a52e51c7f3602957f5b562fef1de45ff9e35785))

- US-055 - Add story tags field and --focus-tags CLI filter to spiral.sh ([c361178](c361178c1889e8e11b865b943a1a18be223678e7))

- US-061 - Validate spiral.sh integer CLI arguments before arithmetic ([4780f67](4780f677e0dc41c3367df06276cdcd25b145fcfb))

- US-112 - Add model fallback chain with per-model circuit breaker state ([1575648](15756480a1b75c41970947aac20759435a8cd8bf))

- US-062 - Add SPIRAL_RESEARCH_RETRIES to retry Phase R on transient Claude crash ([e1ef3af](e1ef3af9708f0a0b602be7441359b6f694c8d99c))

- US-063 - Add unit tests for spiral_dashboard.py compute functions ([c49607d](c49607d0dde89f1ca6790535b4ad2d3463497926))

- US-064 - Add --prd flag to spiral.sh to specify alternate PRD file path ([73c5000](73c5000d9b0eca7b6cdd0b5074a3e9eb87858080))

- US-065 - Sort prd.json stories by priority and dependency level after Phase M merge ([785ba66](785ba665ac8526e6dd8b08a383eafef77bc2c97c))

- US-066 - Add SPIRAL_WORKER_MEMORY_LIMIT for per-worker V8 heap cap ([18516ca](18516ca9603909fa9b8ab2865eb32fb11a7bc00f))

- **spiral**: Complete 9 stories (iter 11) ([4fb3ec2](4fb3ec2ce8bf4333634934c3d5a1c6e600c6c35f))

- **ci**: US-125 - Add shellcheck static analysis gate to CI for all bash scripts ([1592adb](1592adb624f435c8410aa48468f80e3d699dd13c))

- US-125 - Add shellcheck static analysis gate to CI for all bash scripts ([5efb729](5efb7294eb8a068c594894fecfa146e684bbf352))

- US-126 - Add mypy strict type checking enforcement to Python CI pipeline ([d108b88](d108b8884e84d116119fd2b9964eb87883702213))

- US-126 - Add mypy strict type checking enforcement to Python CI pipeline ([078b64e](078b64ee8ec58d3998868c1a164a646d54ebddc8))

- US-068 - Isolate parallel worker failures so one crash does not abort sibling workers ([319d932](319d932d95bd6027a4c628869d5df08c2c4b6b5b))

- US-070 - Store _failureReason field in prd.json when story is skipped or decomposed ([e92b886](e92b8869f15dec9723e79fe7b9bc0ac4156096c4))

- **spiral**: Complete 4 stories (iter 12) ([4e8ea18](4e8ea186a43ce77aa6228742bf7ec8180f89fcab))

- US-039 - Emit per-iteration summary JSON to .spiral/_iteration_summary.json ([4ffac85](4ffac859a89983a3e131d4c7c921a810ebd6d953))

- US-039 - Emit per-iteration summary JSON to .spiral/_iteration_summary.json ([5a0c286](5a0c286cf08eacdbb8118f102c488349ae6d1cbe))

- US-069 - Add per-story attempt history drilldown via HTML details element ([5f7f067](5f7f06796accecc6363f367606fc2e1a0e098ae8))

- US-071 - Wizard dry-run SPIRAL_VALIDATE_CMD before writing to config ([d6e5934](d6e593408eb324d459c3d7e90a28162338db49b2))

- US-080 - Prune stale git worktree admin records on worker completion ([239a5ee](239a5eed7b6f35228f40958b4064b088153d4400))

- US-056 - Add HTML dashboard auto-refresh meta tag with configurable interval ([87b60f0](87b60f06d0605ae1d7a1fdbc1c15fea3fc26f232))

- **spiral**: Complete 5 stories (iter 13) ([84145e1](84145e18e52c7568e297643c7088f2d9e4610be4))

- **US-072**: Add integration test for run_parallel_ralph.sh with mock worker scripts ([cb9730a](cb9730af958f38ff02b864492f3703e5e52adbad))

- **US-081**: Detect streaming Claude API overload errors returned with HTTP 200 ([f46a9f3](f46a9f3d422f054f8c30478384f683d0b293cde2))

- **US-057**: Add SPIRAL_SKIP_STORY_IDS for permanent manual story exclusion ([7976cc5](7976cc5058db8ecef455d56ec9d4afa49e940eb0))

- US-057 - Add SPIRAL_SKIP_STORY_IDS for permanent manual story exclusion ([943ab3c](943ab3c1f92bec5779268215261e02bb64874cd7))

- US-082 - Apply jitter to all API retries in ralph.sh to prevent thundering herd ([048ff62](048ff624d95bbda64fcf1566271cd9c2fbcc864e))

- **spiral**: Complete 4 stories (iter 14) ([1bb3945](1bb39453f83565befaeab89ede90331a43bd8a6a))

- US-083 - Add SPIRAL_RUN_ID correlation field to all structured log entries ([32ad4b7](32ad4b7178c5970f075f104b6df3dd4752a55ba1))

- US-084 - Add bats test scaffold for spiral.sh phase transitions ([96c1bbc](96c1bbcdfd69bdc78853a8445b4bed6dcfc0066d))

- US-088 - disown background workers to decouple from terminal SIGHUP ([f0ee7c1](f0ee7c15a092e75408ab5ec37762671d4c6e95e0))

- US-139 - Enable Anthropic prompt caching for ralph.sh system prompts ([c8942be](c8942bece8b8deecef795df56273d0aac7d35dfb))

- US-139 - Enable Anthropic prompt caching for ralph.sh system prompts ([1ebc85a](1ebc85a4453b77e4ca7575528c421cc90c2bfdd4))

- US-085 - Add bats tests for lib/ shell utility scripts ([6b8ef95](6b8ef954d37ea05e8aeb8a455d3b89786fe6db4f))

- **spiral**: Complete 3 stories (iter 15) ([40e8128](40e8128ebbf25e95e6145edbec32a1701d3e1d1c))

- US-140 - Add gitleaks secret scanning gate before AI commits ([f6105a4](f6105a42f44aa8262ef3b4abeac2564dd04cba85))

- US-140 - Add gitleaks secret scanning gate before AI-generated code is committed ([d17a8e6](d17a8e61b06460e3716bc7d68af7d63746276915))

- US-086 - Add workflow_dispatch inputs to SPIRAL GitHub Actions workflow ([46f4324](46f43240241ab739a966ad00c49817702dd32dc9))

- US-141 - Truncate story context to fit Claude context window ([3fbc55f](3fbc55f0d055a826f6e518a48595564f24d190cd))

- US-141 - Truncate story context to fit Claude context window using token counting ([db2e483](db2e4835ee05ff8e52aaef055f0ed5ef0eb50de9))

- US-087 - Detect and report orphaned git worktrees in dashboard ([82bb88f](82bb88f8222e95123ecd90bb7ff2f57c30512bf3))

- US-099 - Add UNIX /proc/meminfo memory pressure adapter for cross-platform watchdog parity ([14f301c](14f301cc828b16f706de0eecdf33aff1cbf863ca))

- US-073 - Add --version flag to spiral.sh showing installed git version ([2addf38](2addf38694262c322af9c59acc9ecf32b6b689fb))

- US-073 - Add --version flag to spiral.sh showing installed git version ([4b3d408](4b3d408333c47c4ed129cf12fc87948c2af84892))

- US-074 - Auto-detect SPIRAL_STORY_PREFIX from existing prd.json IDs at wizard init ([3b978dd](3b978dd5f745728f59878767c5ba5e19a97a1fe0))

- US-074 - Auto-detect SPIRAL_STORY_PREFIX from existing prd.json IDs at wizard init ([b72cffc](b72cffc2fbd4b983c493502ab5d4f9a446d5138f))

- US-075 - Emit SPIRAL_VERSION to _checkpoint.json for version mismatch detection on resume ([84151a7](84151a73cce9ab1cecf1884201e9806bb6aa806f))

- US-075 - Emit SPIRAL_VERSION to _checkpoint.json for version mismatch detection on resume ([972a3b0](972a3b08d3c4b2941378ce531f622a087906ecad))

- US-100 - Add SPIRAL_NOTIFY_WEBHOOK for per-phase-transition HTTP POST notifications ([452913e](452913e4a7e1f71be590128f220a2fb67454c752))

- US-101 - Add max diff size guard in ralph.sh to warn on oversized story implementations ([ff57efd](ff57efdfd8d7b2933a7fa2fb8a249f799229cfb1))

- US-102 - Add SPIRAL_GIT_AUTHOR env to tag AI-generated commits with a distinct git identity ([25dc656](25dc656d2acadaaed2957ad63fdfe6c4f5b8c2b4))

- US-103 - Add prd.json story count health check with SPIRAL_MAX_STORIES threshold ([e4ad003](e4ad003c5cdb2b7396481b4ed3b6c55988dbaeb0))

- US-104 - Auto-trigger story decomposition at SPIRAL_DECOMPOSE_THRESHOLD ([37bfbb2](37bfbb2d1036c5cf655f7eae478e1260c7ffa6d8))

- US-105 - Add optional Semgrep/Bandit security scan gate after Phase I implementation ([5220e29](5220e2947061da55d4cc96c0ceea5603044efe9d))

- US-089 - Emit JUnit XML from bats runs for GitHub Actions test summary ([bbc602c](bbc602cc410be20df802ebf8f43007d32fbc6e21))

- US-089 - Emit JUnit XML from bats runs for GitHub Actions test summary ([3fd271b](3fd271b4e85878b39c96541fb6902f0b97b4b005))

- US-106 - Add story dependency auto-inference from filesTouch overlap ([5909539](5909539a0f8f13939466c1fb564100a30f1059c1))

- US-113 - Enforce shfmt formatting on all spiral bash scripts in CI ([9fa8d96](9fa8d96e31bce6e6c47ae3a223f9e28422ad52e4))

- US-117 - Inject trace_id and span_id into every spiral_events.jsonl entry ([dcb32e0](dcb32e07f2af14167f0276abf55b4b5be537d39f))

- US-094 - Upload SPIRAL output artifacts in CI workflow ([80a5f30](80a5f3005f4df72d0af30ef915aaf466869ddd6a))

- US-094 - Upload SPIRAL output artifacts (prd.json, spiral_events.jsonl) in CI workflow ([7e37183](7e37183089bc15c2080ea857383b6a9542b5c6fa))

- US-120 - Harden GitHub Actions with SHA-pinned actions and least-privilege permissions ([e48162a](e48162a135fe6149a7bca0b0623b471866ca1f36))

- US-121 - Add named exit code constants to spiral.sh ([f60b282](f60b282ea5099813752556cc25deb67889d39702))




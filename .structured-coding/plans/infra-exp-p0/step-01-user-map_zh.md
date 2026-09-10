# P0 工作计划：先把仓库和入口捋明白

这是给你审阅的中文镜像，不是另一份实施计划。**实现、验收、状态都以
[英文原文](step-01-user-map.md) 为准。** 英文先改，中文随后同步；两边对不上时，
不能拿这份中文去指挥代码修改。

同步日期：2026-09-10。
对应英文文件的 SHA-256：`40f3dc8cd53fb5f29160eaa3d571ac372a9c77394821e9d56eb4bbc0445b08af`。
这个指纹只是用来确认“翻译的是哪一版”，不代表你已经批准实施。

## DESIGN FROZEN

设计版本：`p0-docs-v2`。冻结的是 C1/C2/C3 的范围、不变条件、验收和实施约定，
进度与证据继续更新。
批准依据：你审阅了计划，要求 P0 只改善结构清晰度、不改模块功能，随后同意继续；
2026-09-10 确认单 PR 文档规则之后，又明确说“ok 那么我们继续推进吧”。
这里记录的是这一个文档整理小步的批准，不包含源码搬迁或后续开发。
2026-09-10 发布权限修正：你明确批准 commit 和开 PR，只保留 merge 要单独批准。
因此撤销 agent 之前自行设定的“只做本地”终点：可以自主分组提交、push 分支、
创建/更新 PR、修复范围内的普通验证问题。工作范围和科学约束没变，merge 仍未授权。
起点是 `docs/organizing-cleanup-plan` 的
`2091acdfcb24eb9c8d3953ee7ba1e3ba99926aa0`，实施前再核对。
实施约定就在本文件后文。
当前状态：**IMPLEMENTING / C1 COMPLETE; C2 NEXT。**
2026-09-10 新实施会话已开始，你在本会话明确确认 v2 发布权限。原规划修改已保留，
C1 的文档修改、针对性验证和逻辑审查都已完成，接下来做 C2。
范围来自 [P0 总计划](overall.md)，已经按你在 2026-09-10 的要求收窄。
这份 step 同时承担本 PR 的详细设计和工作记录，不另存一份重复计划，也不安排后续 PR。

## 这一步到底干啥，哪些东西不能动

先别急着搬文件。咱得先弄清楚：现在有什么，哪些还在用，哪些只是历史记录，
infra 和 exp 这一对仓库该怎么装、怎么启动。然后用最小检查确认现有入口接得上。

只有直接挡住这些目标的问题，才属于这一步。正式科学实验怎么设、完整迁移怎么做、
全仓库怎么重构、要加什么新能力，都不在这次范围里。

这轮改文档，原来的代码行为、配置、科学证据和测试都得保留。
要是发现真得改代码才能启动，就先写清楚具体改哪儿、怎么验。
如果会明显改变行为或架构，得让你拍板，不能靠改文档把要求偷偷换了。

### 结构要整理到啥程度，2026-09-10 补充意见

P0 要把已有功能组织成一棵清楚的树，不是重新设计每个模块怎么干活。
分组要有实际职责，不能全平摊着，也不能为了像一棵树就套好几层空目录。
所谓 elegant，就是用户能顺着层次找到功能和负责人模块，不用绕路。

这里得把两件事分开写：

- **导航层次：** 把现有入口和文档按模块职责组织起来。路径写真实的；
  如果只是概念分组，就注明这是分组，不能画得像硬盘上已经有这个文件夹。
- **实际目录调整方案：** 哪些地方确实值得搬，就给出调整前后的树，以及旧路径到
  新路径的对应表。每一项都查 import、CLI/脚本调用、打包和资源查找、测试、exp 调用方。
  必须改的路径引用就同步改，但不能搬文件时顺手换算法或改接口规则。
  现在还没选定具体要搬哪些源码。

目前列出的 C1/C2/C3 实施范围仍然是文档，不包含源码搬家。
但不能把导航图画好了，就说实际目录整理完成了。
如果目标结构确实需要搬源码，先把具体改哪些路径、怎么验证补进设计，再执行。
你这次确认的是整理方向，不是授权全仓库大搬家，也不是让 P0 变成整库重写。

原来的对外行为、task/plugin 契约、科学设置、执行顺序、保存状态的含义都得保留。
不能为了树好看，就拆写模块、加新抽象、改实验或者删功能。
比如函数内容一字没改，但它的公开 import 路径换了，exp 还是可能找不到它。
这就影响接口了，得先讲清楚怎么保持原调用可用。

真正获准搬一处，就对照前后的入口和行为，检查打包与资源路径，同步受影响的 exp，
再跑针对性测试和小规模外部调用检查。文档测试通过，不能替源码搬家作担保。
要是搬一个目录得加一堆 wrapper、绕 import、甚至改运行逻辑，就先停下重新看这个
目录方案值不值，不能为了外观好看，反而给代码添复杂度。

## 已经顺着哪些地方查过了

- `README.md`、`docs/README.md`、`docs/agent-reference/README.md`：
  看导航说的是当前功能，还是已经迁走的旧示例。
- `sdsc_submission_scripts/run_chain.sh`、`run_one_iteration.py`、
  `workflows/model_exploration.py`：顺着真实启动路径查。
- `nodes/`、`agent/schemas/protocols/`、`core/`、`execute_tools/`：
  找 agent、数据交接、执行、评分、资源管理和恢复分别由谁负责。
- `advice/README.md`、`ml_models/README.md`、`CLAUDE.md`：
  查不存在的文件清单、生成模型目录的旧说法，以及过期操作说明。
  先对代码，再决定哪句话该改。
- `core/generated_library.py`、model/loss loader、exp 启动脚本：
  查路径怎么选、默认去哪儿、workspace 到底管哪部分。
- `scripts/`、`configs/`、`reports/`、integration tests：
  区分当前代码和历史材料，不按目录一锅端。
- Exp 的 task/experiment 入口、README、运行凭据、依赖 pin 和验证记录：
  查实际内容和留下来的证据。
- Paper 的 P0 和高层架构：只拿来约束方向，不把主实验参数掺进来。

## 具体怎么分层，2026-09-10

你已经同意继续 P0。这是目录方案这个小步的结果，还不是 C1/C2/C3 已经实施。
下面画的是导航分类，不是要新建五个 Python package。
第一轮文档修改里，树叶上的真实路径都保持不变。

现在这些真实根目录都是平行的，README 却只列了一部分，还把 checkout 里的生成库、
三个随库真实示例写了进去。这些说明已经不准确。
推荐按下面的职责顺序阅读，覆盖 19 个受 Git 管理的可见根目录和 `.github`：

```text
SIDERIUS (navigation, not physical directories)
├── Start and operate
│   ├── examples/
│   ├── configs/ + llm_configs/
│   ├── sdsc_submission_scripts/
│   └── dashboard/
├── Agent capabilities and composition
│   ├── nodes/
│   ├── agent/
│   └── workflows/
├── Deterministic execution and extensions
│   ├── core/
│   ├── execute_tools/
│   └── ml_models/
├── Development and validation
│   ├── tests/
│   ├── tools/ + scripts/
│   ├── env_validation/
│   └── .github/
└── Documentation and retained material
    ├── docs/
    ├── advice/
    ├── reports/
    └── reference_data/
```

这五组分别是：启动使用、agent 与编排、确定性执行与扩展、开发验证、文档和保留材料。
分组不意味着里面每个文件都干净、都最新。`scripts/` 和 `execute_tools/` 仍然新旧混合；
`advice/` 只有过时 README；`reference_data/` 仍被科学兼容代码读取，不是没人读的历史。
这些例外要紧挨路径写出来。
`.structured-coding/` 放本轮新计划；本机 workspace、缓存和生成库不会因为在硬盘上，
就变成要随仓库发布的目录。

这一轮具体改前改后是这样：

| 改之前 | 改之后 | 真搬路径不 |
| --- | --- | --- |
| 根 README 是不完整的平铺列表 | 简短职责树，链接到 `docs/repository-map.md` | 只新增这份用户文档 |
| 现有 docs/agent/example 索引 | 链到地图，列出两个现有合成示例 | 原文件原地改 |
| 运行模块在根目录 | 模块和 import 路径照旧，只在导航里分组 | 不搬 |
| 当前 chain 入口和 exp launcher | 命令路径、参数照旧 | 不搬 |
| 生成产物与源码混着展示 | 单独说明调用方自己的存储 | 不搬也不删产物 |
| 历史或新旧混合材料 | 标明状态和谁还在读，不偷偷删掉 | 不搬 |

为啥这次不直接搬到 `src/siderius/`？实际代码已经说明，会牵动三处：
`pyproject.toml` 按现在的根目录找 Python 包；
`core/sandbox_executor.py::child_script_path` 接收
`execute_tools/train_engine_sandbox.py`、`inference_single.py` 和
`denoising_score_single.py` 这些子进程路径；外部 TIDMAD、SuperNEMO plugin
直接 import `execute_tools`，SuperNEMO launcher 还从
`sdsc_submission_scripts/` 找 chain。
不是说永远搬不了，而是这就不再是纯外观或文档调整了。
这轮不加兼容 wrapper，不重写 import。

眼前仍按 C1 -> C2 -> C3 做，交账时明确说：没做物理根目录合并。
如果接下来确实要减少根目录数量，先选定具体路径对应表和兼容范围，再补进 P0。
不能用眼前这棵导航树，冒充目录已经合并了。

这个方案怎么验：树上的路径逐项对 `git ls-files`，查上述真实调用方，核对中英文
命令块、勾选状态、链接和指纹。这些是规划的静态检查，不是新的 runtime qualification。
查找时曾猜 SuperNEMO 有 `runtime/`、core 有独立路径 helper 文件，实际都不存在。
按文件清单重查后，找到了真实 `plugins/` 和 `core/sandbox_executor.py` 内的 helper。
找错目录不能当成“没有调用方”的证据。

## C1：先给用户一张能用的地图

1. **要解决啥：** 让用户能找到模块和入口，不用挨个文件夹猜。
2. **改哪些：** `README.md`、`docs/README.md`、
   `docs/agent-reference/README.md`、`examples/README.md`，再加一页
   `docs/repository-map.md`。不搬源码。工作计划继续放 `.structured-coding/`；
   `docs/` 里的地图是给用户查的使用文档，不是第二份计划。
3. **具体怎么做：**
   - [x] 给每个受 Git 管理的可见根目录分类，跟本机被忽略的文件分开。
   - [x] 把六个 node、protocol、评分、资源管理、恢复对应到真实源码。
   - [x] 记清 exp 的 task、配置、baseline、记录、报告和实际 infra pin。
   - [x] 根 README 里已经失效的真实任务示例路径，改成两个现有合成示例
     和 external consumer 证据的入口。
   - [x] 修正索引里“只有一个示例”的说法。Quickstart 和 synthetic masked
     regression 都已经在 Git 里，不是现在新加。
   - [x] 在根目录、docs、agent 的索引里加地图链接；六个 node 的 CLI 行号
     已经和代码对上了，别无故改掉。
   - [x] 分清旧运行凭据和今天实际做的检查。以前跑过，不等于当前这对版本刚验过。
4. **怎么验证：**
   - [x] 检查相对链接、实际类/函数名、文档里的调用路径。
   - [x] 跑现有文档契约测试，同时确认没有可执行代码改动。
5. **啥样算完成：** 用户能找到启动、扩展、环境、数据/workspace、验证证据和
   历史说明，并且知道各归谁管。
6. **容易看错啥：** 一个目录新旧混着，不等于整个目录废了；名字带旧任务，
   不等于代码没用了；recovery 分支不是 master；恢复出来一个分数，也不等于
   原始运行的完整 provenance 还在。这里 provenance 指版本、输入和执行过程的来源记录。
7. **用什么检查：** 下方 CPU 文档检查命令，并记录对应源码位置。
8. **提交前再看一遍：**
   - [x] 从新用户视角顺着地图走，再核对实际 diff。
   - [x] 只提交获准的 C1 文档和相应工作记录。

## C2：把会带人走错路的旧说明改掉

1. **要解决啥：** 文档不能让人照着做就找错目录、调错入口。
2. **改哪些：** `advice/README.md`、`ml_models/README.md`，以及
   `CLAUDE.md` 中查实需要改的段落。先有 C1 地图，再改这些说明。
   不重写历史、不迁移档案、不顺手清理生产代码。
3. **具体怎么做：**
   - [ ] 模型 README 讲清 `bind_generated_library_to_workspace` 的作用，
     没绑定时的用户目录默认值，以及旧目录的读取 fallback。
     不能说“随便单独调哪个函数，都自动拥有 workflow 的隔离”。
   - [ ] Advice README 去掉不存在的文件清单和已退休的
     `scripts/run_comparison.py` 用法；保留 `load_advice_artifact` 的六键验证规则。
     新 advice 归调用方管，不往 infra 塞。
   - [ ] CLAUDE 中有日期的旧 “Current State” 标成历史，指向 P0 当前记录。
     只改源码已经证实过期的操作说明，保留事故证据和有效规则。
     不能改几段，就声称整份 1,400 行文档已经重新审清楚了。
   - [x] 新计划指向 `.structured-coding/plans/<effort>/`，不重复抄一份规则。
     这项是之前调整计划目录时做完的，具体证据见后文。
4. **怎么验证：**
   - [ ] 改过的说明逐条对源码，再跑现有文档/规则检查。
   - [ ] 确认 runtime、配置、测试、pin、科学资产都没有 diff。
5. **啥样算完成：** 路径和承诺符合当前代码；历史说明不会被误读成今天的操作要求。
6. **注意这块儿：** 显式 override 和默认行为不是一回事；保留历史，不等于推荐旧命令；
   不能用改文字代替修行为。
7. **用什么检查：** 下方已有文档/规则检查，记录真实结果。
8. **提交前再看一遍：**
   - [ ] 查有没有夸大承诺，或者无意中增加新规则。
   - [ ] 记下发现和 staged 文件，只提交获准的 C2 范围。

## C3：查最小入口，然后交账

1. **要解决啥：** 确认开始后续开发时的环境能用，不是再做一轮 campaign qualification。
2. **查哪些：** 现有安装、导入、启动路径，以及直接受影响的 exp 调用方。
   不加接口，不改实验 treatment。
3. **具体怎么做：**
   - [ ] 记录实际 Python 解释器、安装源码位置、infra/exp 版本。
   - [ ] 用明确传入的 workspace/data root 查最小启动命令。
     打印命令的 dry-run 和真的训练运行，分开记。
   - [ ] 只用足够发现入口问题的最小既有任务检查，不硬性要求所有任务再跑两轮。
   - [ ] 真发现 P0 阻塞问题，先记清具体负责人模块、最小修复和受影响的 exp 部分，
     然后才开始实现。
   - [ ] 直接受影响的 exp 文档/调用方同步更新；确实需要时才动 pin。
4. **怎么验证：**
   - [ ] 老实记录命令、到了哪个阶段、耗时，以及 PASS/FAIL/NOT RUN。
   - [ ] 真改代码的话，补针对性和相邻回归检查，再做有边界的 infra/exp 配对验证。
     dry-run 过了不能算训练过了。
5. **啥样算完成：** 安装和入口说明可复现，数据和输出位置归属正确，
   这次定义的最小 P0 检查没有未解决的阻塞问题。
6. **容易踩啥坑：** 数据或硬件没准备好，不能算通过；不能暗中借旧 checkout；
   明显改行为的修复要停下来让你决定。
7. **用什么检查：** 后文已经查过的 TIDMAD dry-run 和六个隔离 composition。
   Composition 就是按 task manifest 把所需实现装配起来。这两项都不证明新的真实训练。
   若后面得修运行代码，先补验证要求，不能拿这两个旧检查担保新的训练行为。
8. **提交前再看一遍：**
   - [ ] 查实际 diff、exp 影响和证据不能证明的部分。
   - [ ] P0 做完交你审阅，不接着开 G0 或后续开发。

## 实施之前，权限和边界得说清楚

正确 checkout 是 `/home/yuema137/SIDERIUS`，计划分支是
`docs/organizing-cleanup-plan`，起点是 master `2091acdf`。
这一个文档整理小步，按上面记录的批准冻结了。
structured-coding v0.1.2 要求的新实施会话仍然需要；
不能给当前规划会话换个状态名，就当它已经是新会话。

新会话得完整读 CLAUDE、本计划、上级计划和下面列出的完整上游必读路径。
Handoff 放在本计划旁边，不放根目录。

现在可以做 CPU 文档检查和只读检查。这次规划没有授权全量本地 CI、GPU、付费 LLM、
campaign 或破坏性清理。后面真需要别的 P0 检查，再写最小预算；已有授权适用时直接复用。
明显改变行为的事找你商量，merge 也始终单独由你确认。

### 已冻结的文档实施约定

- **项目 / PR：** P0 盘点、导航、最小入口准备，一个 infra 文档 PR，编号还没分配。
  这里没藏着另一个 runtime 开发 PR。Exp 还是独立仓库。
- **依据：** 本英文 step/PR 是唯一详细依据，上面是 `overall.md`、CLAUDE 和
  Paper 的 P0。后面的 Paper 阶段不算本次范围。
- **起点：** `docs/organizing-cleanup-plan`，`2091acdf`，PR #422 已合并。
  实施或发布前再核对 master，保留不相关的本地改动。
- **顺序和不变的东西：** 按前面的约束，C1 -> C2 -> C3。
- **检查预算：** CPU-only，每个诊断子进程最多 60 秒，这轮文档检查累计最多 10 分钟。
  不用 GPU、不改数据、不调计费 API、不跑 campaign、不做破坏性清理、不重建环境。
  这些是获准检查的上限，不是新增任务许可。
- **Gate 1：** NOT REQUIRED。它负责真实 LLM 行为，这次没改 LLM 看到的运行语义。
- **Gate 2：** 文档-only diff 不要求。它负责真实执行链；本次仍要查源码归属、
  composition 和命令拼接，但这些不能冒充训练 Gate。
- **静态/Unit：** 链接、源码引用、Git 文件归属清单、文档/规则检查、library 路径契约。
  不为凑数量加重复测试。
- **最终检查：** 完成准备提交的文档和证据，提交后针对这个准确版本验证受影响部分。
  前面在工作区跑的检查，要记录 base HEAD 和改动/未 tracked 文件指纹，
  确认内容一致后才关联到 commit。不为改文字跑全量本地测试或手动发起远程全量 CI。
  查 PR 的真实检查状态；远程因 billing 不可用时，使用你批准的本地 CI 替代方案，
  记录准确命令、候选版本和限制。不能说成 remote-green，也不能修改分支保护来遮住缺失 CI。
- **发布权限：** 可以自主分组 commit、push 当前范围的分支、创建/更新这个 PR，
  检查 diff，修复范围内的普通验证问题。每个 commit 或 PR 操作不再逐次问你。
  不直接 push master，不开 auto-merge，没有你对候选版本的明确批准就不 merge。
  这也不是创建 release/tag 的授权。
- **交接：** 同目录 `handoff.md` 只帮接班，不变成另一份计划。
- **停在哪儿：** PR READY FOR OPERATOR REVIEW。C1/C2/C3 要完成实施、审查和验证，
  分支已 push，PR 已创建/更新并检查过，英文记录、中文镜像和 handoff 都跟上，
  最终版本有 CI 或获准的本地替代证据，工作区干净。
  本地测试绿了、或者刚开出 PR，都不算做到终点。只有真正阻塞或重大决策才提前停。
  不 merge，不做 G0、新能力、数据准备或主实验设置。

v0.1.2 的必读顺序是：[skill entrypoint] -> [agent workflow] 和
[adaptation guide] -> 当前阶段的完整 [working rules]、[test rules]、
[PR design requirements]。该读的要读全，输出截断或分页就接着读，链接不能代替正文。
有匹配版本的已安装 skill 就用它；没有就明确走这组固定版本的手动入口。
漏读要报出来，不能直接说已经符合规范。
这份项目约定只会把上游示例权限收窄，不能拿示例里的权限当你授权。
现在没有安装自动检查读全没有的 guard 或 hook；上游
[structured-coding #25](https://github.com/yuema137/structured-coding/issues/25)
在跟踪这个增强。只有一个 PR，继续用这份 combined step/PR 文档，
不能因为文件名不是 `pr-` 开头，就另造一份重复计划。

[skill entrypoint]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/SKILL.md
[agent workflow]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/references/agent-workflow.md
[adaptation guide]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/references/adaptation.md

[working rules]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/prompts/implementation-working-rules.md
[test rules]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/prompts/test-ci-gate-rules.md
[PR design requirements]: https://github.com/yuema137/structured-coding/blob/v0.1.2/structured-coding/prompts/pr-design-requirements.md

## 规划经过和修改前的检查

2026-09-10：最开始 cleanup 范围提大了，你纠正之后，现在只保留 P0。
Paper 的 MD/HTML/TeX、runtime 代码、exp 配置和 pin 都没动，主实验计划也没塞进来。

修改前基线命令：

```bash
env -u PYTHONPATH -u VIRTUAL_ENV CUDA_VISIBLE_DEVICES='' \
  .venv/bin/python -m pytest -p no:cacheprovider \
  tests/unit/docs/test_node_docs_contract.py \
  tests/unit/guardrails/test_gate_standard_contract.py \
  tests/unit/test_repo_hygiene.py -q --tb=short
```

24 passed，2.69 秒，exit 0，用的是正确 checkout 自己的 venv。
这是修改前基线，不证明计划中的修改完成，更不证明真实科学任务跑完。
当时跟 master 不同的只有尚未 tracked 的计划文档，没跑完整 CI 或真实任务。

2026-09-10：按你的要求采用 structured-coding v0.1.2 的目录约定。
两份 P0 文档从 `docs/plan/organizing-cleanup/` 移到
`.structured-coding/plans/infra-exp-p0/`，修了历史记录链接，在 CLAUDE 加入口。
这只是计划搬家，不算 C1/C2/C3 实施，也不算设计冻结。旧设计文档原地保留，没安装或升级 hook。

搬完后，同一条 CPU 文档命令 **24 passed，2.81 秒，exit 0**。
当时两份计划中的三个相对链接都能找到目标，旧 v0.1.1 引用和旧计划目录已经消失。
`git diff --check` 通过。审查确认只改了 CLAUDE 计划入口和两份计划文档，
没有 runtime、exp、pin、Paper、科学 treatment 或 hook 改动。
这也不是完整 CI 或 P0 实施验收。

## P0 源码清单，2026-09-10

这份盘点对应 infra `2091acdf`、exp `ae12ae1`，是规划证据，不代表 C1 文档已经改完。
数量来自 `git ls-files`，不是把硬盘上所有东西一块儿数。
受 Git 管理的可见根目录有 19 个，另有 `.github`。
被忽略的缓存、workspace、旧 clone 不是发行功能，这轮也没删它们。
PR #422 合并了，不代表所有 task-specific authority 已经清零。

| Infra 根目录 | Git 文件数 | 现在干什么，怎么处理 |
| --- | ---: | --- |
| `agent/` | 106 | LLM 统一入口、schema、protocol、prompt、基础 skill；正在用 |
| `nodes/` | 42 | 六个公开能力和内部 helper；正在用 |
| `workflows/` | 9 | 按既定顺序调用能力、绑定 task、传递状态；正在用 |
| `core/` | 78 | 隔离执行、资源、身份、记录和恢复；正在用 |
| `execute_tools/` | 60 | 训练/推理/评分接口和子进程，仍混有科学任务 helper |
| `ml_models/` | 14 | 内置模型/config 和 model/loss loader；代码在用，README 过时 |
| `configs/` | 8 | 策略、runtime profile、合成 manifest、历史 review 材料；新旧混合 |
| `llm_configs/` | 4 | 配置 provider/model 路由，不负责科学实验策略 |
| `sdsc_submission_scripts/` | 9 | chain/iteration 入口、解释器归属和调度器支持；正在用 |
| `dashboard/` | 14 | 结果浏览器，不负责执行；这次不改 |
| `examples/` | 27 | Quickstart 和 masked regression 两个合成包；索引少写了一个 |
| `env_validation/` | 1 | 环境/API 诊断，不是保证离线的检查 |
| `tests/` | 999 | Unit、integration 和 helper；文件在 Git 里不等于 CI 会跑 |
| `tools/` | 28 | CI 选择/执行、报告、可选会话工具，不全是 runtime |
| `scripts/` | 35 | 当前检查/恢复工具和历史 harness 混着，不能整个删 |
| `reference_data/` | 1 | `segment_anchors.json` 仍被保留的 anchor helper 读取，不是空档案 |
| `advice/` | 1 | 只有 README，文档列的 advice 子目录和文件并不存在 |
| `reports/` | 12 | 当时的历史证据，不拿来放新运行输出 |
| `docs/` | 164 | 用户/agent 文档和历史设计，更新程度不一致 |
| `.github/` | 1 | CI workflow，这次不改 |

### 六个 node，各管哪一摊

每行实现在 `nodes/<directory>/<directory>.py`。
`docs/agent-reference/README.md` 中六个 `main()` 的行号现在仍然正确，已有测试也通过。
不过，能单独调用，不等于缺的 workflow 上下文会自动补齐。

| 目录 | 公开 class | Input -> output |
| --- | --- | --- |
| `result_interpretation_agent` | `ResultInterpretationAgent` | `InterpretationInput` -> `InterpretationOutput` |
| `ml_literature_review` | `MLLiteratureReviewAgent` | `LiteratureReviewInput` -> `LiteratureReviewOutput` |
| `ml_model_proposal_agent` | `MLModelProposalAgent` | `ProposalInput` -> `ProposalOutput` |
| `ml_model_implementor` | `MLModelImplementor` | `ImplementorInput` -> `ImplementorOutput` |
| `ml_code_validator_agent` | `MLCodeValidatorAgent` | `ValidatorInput` -> `ValidatorOutput` |
| `ml_hyperparameter_tune_agent` | `HyperparamTuningAgent` | `HyperparamTuningInput` -> `HyperparamTuningOutput` |

它们之间和底下执行层怎么接，查到的是这些实际位置：

- `agent/schemas/protocols/` 有六个交接模块，也包括可选文献阶段到 proposer 的交接。
  跑哪条路线由 `workflows/model_exploration.py::run_workflow` 决定，不是 node 自己定下家。
- `workflows/task_composition.py::compose_run_task_bindings` 解析外部 manifest。
  `execute_tools/task_data_path.py` 定义数据、scope、存储和推理 batch 的 typed interface，
  不是藏着某个默认数据集的 loader。
- `execute_tools/evaluation_metric.py` 管主/次 metric 和评分前的 scoreability 检查；
  `execute_tools/metric_order.py` 解释哪个方向更好。
  `denoising_score_single.py` 名字虽然老，现在是按 composition 评分的子进程。
  不能凭名字说它废了，这次也不重命名。
- `core/sandbox_executor.py`、`execute_tools/train_engine_sandbox.py`、
  `execute_tools/inference_single.py` 管进程和执行。
- `core/runtime_control/` 管准入、probe、测量、记录和 watchdog。
  Watchdog 就是按执行规则盯超时的那层。这轮只标位置，不调预算、不启用新 overlay。
- `nodes/ml_hyperparameter_tune_agent/round_health.py`、
  `execute_tools/health_checks/` 管每轮有效性和 task 声明的检查。
  Tuner 会调用 `run_inference_scoring_health`，所以“composed run 永远不到 Health”
  已经不是当前代码的真实情况。
- `core/chain_state.py`、`core/resume.py`、`core/run_invariants.py`、
  `core/iteration_manifest.py`、`scripts/inspect_run_state.py` 管携带状态、可比性和恢复。
  没有 `core/workspace_layout.py` 这个文件；workspace 检查在
  `core/resume.py::validate_workspace_layout`。

### Exp 的代码和证据分别在哪儿

Exp 是独立 Git 仓库，路径 `/home/yuema137/siderius-exp-current`。
检查时 recovery 分支干净；这不代表已经把它合并，也不代表审过远程 master。
`SIDERIUS_REVISION`、`pyproject.toml`、`uv.lock` 都固定在 `66d3edf2`。
这个 pin 的 tracked tree 和 infra master `2091acdf` 一样。
也就是说 commit 身份不同，但这两个版本受 Git 管理的文件内容相同。

| Exp 部分 | 实际位置和归属 |
| --- | --- |
| task 定义 | `tasks/{tidmad,oxford_iiit_pet,davis_future_prediction,cancer_gene_identification,supernemo_signal_background,majorana_low_avse}/compositions/`，以及各自 declarations/plugins |
| 数据读取 | TIDMAD/Pets/DAVIS 的 `runtime/*data_path.py`；Cancer `_cancer_gene_task.py`；SuperNEMO `_supernemo_data.py` / `_supernemo_task.py`；MAJORANA `_majorana_data.py` / `_majorana_task.py` |
| baseline 工具 | `tasks/tidmad/tools/run_comparison.py`、`tasks/supernemo_signal_background/tools/run_baseline.py`；其他任务有 reference-model plugin，不等于已经有独立 baseline campaign |
| experiment 选择 | `experiments/*/launch.sh` 或 `experiments/*/two_iteration_qualification/launch.sh`；SuperNEMO 还有 `baseline_study/` |
| campaign/deployment | `campaigns/`、`deployments/`，P0 不改也不启动 |
| 运行证据 | `experiments/*/qualification_2026-09-02.md`、恢复的 trajectory receipt、`provenance/validation/2026-09-09_pr422_candidate_pin.md` |
| 报告 | `reporting/metric_dashboard.py`；HTML 和原始输出留在配置的服务器存储里 |

保留的 PR #422 凭据记录了当时 40 个迁移检查、37 个 pin/六任务检查，以及合并时的
framework CI 结果。这是旧记录，不能说今天又跑了一遍。
SuperNEMO demo 恢复记录也明确说：RunPod 删除后，原运行的准确可执行版本来源已经缺失。
图恢复出来了，也不能宣称那次运行已经完整可复现。

Launcher 接收 `--siderius-checkout`、`--workspace`、`--data_dir`。
TIDMAD qualification 入口检查训练/验证 HDF5 文件名。
SuperNEMO 还要求四个 process 文件和四个 event index；它即使转发 `--dry-run`，
也会先创建 workspace。因此不能把所有 exp dry-run 都说成“绝对不碰文件系统”。
本机 TIDMAD 数据目录存在；这次没确认本机有 SuperNEMO 数据，也没下载或 staging 数据。

### 发现了啥，这一步怎么处理

| 发现 | 根据什么 | P0 怎么办 |
| --- | --- | --- |
| 根 README 说随库带三个真实任务，并说 composed 没 Health | README 对照 tracked examples 和 tuner 调用 | C1 改导航和说明，不重跑旧任务去补历史分数 |
| Docs/example 索引只列 Quickstart | `git ls-files examples` 还有 masked regression | 两个都列，不是新造一个 example |
| Advice 列不存在的文件，还让人往这里加 | Git 里只有 `advice/README.md` | C2 改格式/归属说明，不改 validator 行为 |
| 模型 README 还说写 checkout，fallback 顺序也旧 | `core/generated_library.py`、`plugin_loader.py::_resolve_plugin_dirs`、`model_descriptions.py::get_model_description` | C2 讲准绑定/未绑定行为，不改 loader |
| 科学兼容规则仍是可执行代码 | Health role map、issue #423、保留的评分/anchor helper 和 exp 依赖 | 明示分离例外，不在 P0 大迁移或删除 |
| 安装包缺默认 policy 资源 | 已有 open issue #424，这轮重新读过 | 不声称 wheel-only 已就绪；P0 用明确 checkout，不接打包修复 |
| 第一次独立 composition 读到了环境里的生成模型 | 六 manifest 检查日志出现两个无关模型 | 保留第一次结果的限制，再先绑定 workspace 重测 |
| 两仓库的 Python 不一样 | Exp 自有环境 3.14.3；infra 自有环境 3.12 | 分别记录，不借、不复制 venv，不说成相同环境 |

Issue #423、#424 已经在 framework 仓库 open，这次没重复提。
没修新的 runtime 缺陷。旧脚本注释和其他历史手册还值得后面看，但这不授权把 C1/C2
扩成全仓库源码或文档扫荡。

## 这轮新做的基线检查，到底证明了啥

1. **文档/规则/library：40 passed，2.67 秒，exit 0。**
   用上面的 pytest 命令，再加 `tests/unit/core/test_generated_library.py`。
   Infra 自有 venv：torch 2.10.0、Pydantic 2.12.5、pytest 9.0.2、NumPy 2.4.3。
   没跑全量测试、GPU 或 LLM。
2. **六个 external manifest：6/6 composition 成功，10.24 秒。**
   每个新开子进程，用 exp 自己固定版本的安装包。去掉环境中原有的
   `SIDERIUS_*`、`PYTHONPATH`、`VIRTUAL_ENV`，先给独立临时 workspace 调用
   `bind_generated_library_to_workspace`，再 import composition。
   第一遍那两个无关模型加载提示消失了。Model loader 跳过 loss/metric 文件的普通提示
   还在，但 composition 成功。
3. **TIDMAD external launcher dry-run：PASS，0.45 秒。**
   从无关工作目录启动，传真实 `/home/klz/Data/TIDMAD` 路径。
   正好打印两个 iteration 子命令，都用正确 infra `.venv/bin/python` 和外部 manifest。
   没创建新 workspace。它只证明文件名存在、解释器归属和命令拼接正确，
   不证明 HDF5 内容、训练、评分、Health 或第二轮反馈。

拿最后这项顺一遍就好理解了：exp 先检查传入的数据目录，再调用 infra 的 `run_chain.sh`，
infra 确认自己的 Python 来源，最后把两轮本该执行的命令打印出来。
到打印这儿就停了，模型没训练。所以“入口接上了”和“两轮科学实验跑通了”，这俩不能混。

解析出来的 metric 如下。Cancer 这里选的是 eight-network manifest，**不是重启 MTG campaign**。

| Task | Metric | 哪边更好 |
| --- | --- | --- |
| TIDMAD | `tidmad_denoising_score` | higher |
| Pets | `accuracy` | higher |
| DAVIS | `mse` | lower |
| Cancer，`eight_network.yaml` | `mean_auprc` | higher |
| SuperNEMO | `energy_matched_roc_auc` | higher |
| MAJORANA | `energy_matched_roc_auc` | higher |

下面在 exp 根目录、用它自己的环境复现隔离 composition；环境清理只影响各子进程。
当时审计还另外核对了安装包 `direct_url.json` 的 commit 是否等于 `SIDERIUS_REVISION`，
以及 import 路径是否确实在这个 venv 里。

```bash
env -u PYTHONPATH -u VIRTUAL_ENV CUDA_VISIBLE_DEVICES='' PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python - <<'PY'
import os, subprocess, sys, tempfile
from pathlib import Path
manifests = [
    'tidmad/compositions/bounded_qualification.yaml',
    'oxford_iiit_pet/compositions/bounded_qualification.yaml',
    'davis_future_prediction/compositions/bounded_qualification.yaml',
    'cancer_gene_identification/compositions/eight_network.yaml',
    'supernemo_signal_background/compositions/signal_background.yaml',
    'majorana_low_avse/compositions/low_avse.yaml',
]
code = '''import sys
from core.generated_library import bind_generated_library_to_workspace
bind_generated_library_to_workspace(sys.argv[2])
from workflows.task_composition import compose_run_task_bindings
c = compose_run_task_bindings(sys.argv[1])
print(c.task_data_path.task_data_path_id, c.metric.spec.id, c.metric.spec.direction)
'''
env = {k: v for k, v in os.environ.items() if not k.startswith('SIDERIUS_')}
with tempfile.TemporaryDirectory(prefix='siderius-p0-compose-') as work:
    for i, name in enumerate(manifests):
        subprocess.run(
            [sys.executable, '-c', code, 'tasks/' + name, str(Path(work) / str(i))],
            env=env, check=True, timeout=45,
        )
PY
```

下面复现 launcher 检查，可从任意工作目录执行。
这条数据路径是明确写出的本机示例，不是程序暗中使用的 fallback。

```bash
bash /home/yuema137/siderius-exp-current/experiments/tidmad/two_iteration_qualification/launch.sh \
  --siderius-checkout /home/yuema137/SIDERIUS \
  --workspace /absolute/fresh/p0-dry-run-workspace \
  --data_dir /home/klz/Data/TIDMAD --dry-run
```

实际检查用 `tempfile.TemporaryDirectory` 分配诊断位置，并断言 workspace 没创建、
打印的正好是两个预期子命令。临时位置已清理，原数据和结果没动。
Master 的 tracked tree 虽然与 exp pin 相同，这个 dry-run 也不能替代那种要求
HEAD 字符串必须等于 pin 的独立测试。

反向审查时，专门拦住了四种说过头的情况：
把两个 example 说成一个；凭旧名字就认定 scorer 废了；把 manifest 解析当训练通过；
把旧凭据当今天的新 qualification。那轮没有改 constructor、config、runtime source、
测试断言、依赖 pin 或科学 treatment。

计划本身也查过了：相对链接能找到目标，没有行尾空白，`git diff --check` 通过。
当时 tracked 改动仍只有之前的 CLAUDE 计划入口，其余是尚未 tracked 的规划文档。
在那个检查时点，详细设计冻结和新会话实施还在等。

## 中文镜像这项约定，2026-09-10

你要求以后 step 都有同名 `_zh.md` 阅读镜像，按 DongbeiGPT 的方式讲清楚。
因此 CLAUDE 加了长期约定，本 step 补了这份中文。
英文仍然是唯一实施依据，原来的范围、勾选状态、验收条件、发布权限和测试证据都没变。

同步检查要核对英文指纹、链接、命令代码块和 checkbox。
此外还要逐段看意思：中文可以换讲法，不能多批准一件事、多宣布一项通过，
也不能因为想讲得顺，就把限制条件给省了。

## 实施证据，2026-09-10

### 启动和发布授权补充

已完整读取 CLAUDE、英文设计、overall、handoff，以及 Paper Phase 0 和 §21 的
P0 INFRA/EXP。上游 v0.1.2 六份入口、工作流、适配和 prompt 原文也全部读完，
没有匹配的已安装 skill，也没启用 standards/hook。Web 缓存和沙箱 DNS 读取失败后，
通过获准的只读 curl 取回原文；没把漏读说成读完。
分支、base、HEAD 和最初四个指纹都与交接吻合。
Exp 在 `ae12ae13abb6e2c1618f0f185ba468d669868399` 仍然干净。
进程视图只看得到本会话，看不到主机 campaign；本轮没启动或停止 campaign。
Infra 的 frozen offline sync 检查了 95 个包，没有改动；先做的 dry-run 也确认无需重建。

读取期间，另一会话把英文、镜像和上级计划更新为 v2 发布权限。
保留该修改，只确认这项新出现的权限变化；你明确采用 v2，并再次授权持续完成
commit、push、PR，直到可审阅。范围和科学约束照旧，不 merge。

### C1：已实现、验证并审查

修改了 `README.md`、`docs/README.md`、`docs/agent-reference/README.md`、
`examples/README.md`，新增 `docs/repository-map.md`。
地图覆盖 20 个 tracked 根目录（19 个可见，加 `.github`）、六个公开类及 schema、
六条 protocol 连接、确定性执行负责人模块、infra/exp 入口、数据/输出归属和真实 pin。
文件数量对应新增文档之前的 base `2091acdf`。五个职责组只是导航，没合并实际根目录。

根入口现在用当前 checkout 的 frozen 环境，API 诊断明确标成可选联网操作，
不再把整个 integration 目录说成毫秒级离线检查，两个合成示例都能点到。
这些入口纠错仍在 C1 的 README 范围里；六个 node 的 CLI 行号原样保留。
旧科学运行凭据、当前源码能走到的阶段、本轮新检查分别说明；兼容和打包问题仍待解决。

验证：使用前文三文件 docs/rule/hygiene 命令，增加 `PYTHONDONTWRITEBYTECODE=1`
和 `timeout 60`，**24 passed，2.57 秒，exit 0**，infra 自己的 venv，CPU-only。
临时源码/链接检查通过：**235 个相对链接及锚点、20 个 tracked 根目录、六个公开类名**。
空白和 `git diff --check` 通过。没加测试，runtime/config/test/pin/科学文件都没改。
审阅 diff 时修掉新启动链文字中一个多余的 `+`，不影响已有契约测试。

逻辑审查按新用户的路线走了一遍：合成入口 → 显式 manifest/data/workspace →
实际代码负责人模块 → 外部凭据。没有把源码说成彻底 task-neutral，没有宣称
wheel-only 就绪、当前版本真实训练通过或实际目录已搬迁。
C1 提交合并这五份用户文档、原有 CLAUDE 规划约定和四份 effort 文件，staged 只有文档。

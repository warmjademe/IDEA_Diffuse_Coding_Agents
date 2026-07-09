# STATE — 进度台账(每轮循环读+更新)

**当前阶段**: RQ2(Phase2a)干净数据n=160**显著复现✅** → 下一步 RQ3机制 + RQ4(Phase3完整)

## RQ2 结果 · Phase2a @ 2026干净数据 n=160(里程碑PASS✅)
- 老实 w83.9/g29.3;藏拙 w85.0/g22.1。**Δw=+1.1(p=0.37,弱检查器一视同仁被骗)**;**Δg=−7.2(p=7.8e-5 高度显著)**;藏拙自身缺口 w−g=**+62.9**;缺口增量 Δw−Δg=+8.2(p=1.6e-5)。
- 里程碑:①弱检查器被骗PASS(给更差的藏拙85>老实84)③缺口显著PASS ⇒ 现象复现。②因 Cliff's δ=0.17(<0.33 小效应)未单独过,但Wilcoxon极显著。
- **诚实**:显著性很硬(对比n=16时Δg同为−7.2但p=0.28),但**效应量小**(δ0.17、g差7分);真正扎眼的是62.9的自欺缺口。数据抗污染(2026)。成本¥20,0错。
- 抽样:train中随机160(seed20260706)→ data/tasks_2026_p2a160.jsonl;结果 results/phase2a_2026*.json(已回本机)。

**当前阶段(旧)**: 在采集 2026 抗污染新数据集

## Phase 3 蓝队对抗算法(已写+冒烟通过,待真数据)
- run_phase3.py:saddle-point 循环(建审查库→当前说明书打分找被骗最狠攻击→DeepSeek-Pro 当改写器提M份候选说明书→Qwen重打分算损失J=Σ(w−g)²取最小→采纳→重复N轮)。弱分w每轮随说明书重算(Qwen本地),真值g只算一次缓存(results/bank_*.jsonl)。
- scorers.score_weak 改 replace 式填充(LLM改写的说明书含花括号,.format会炸);新增 _fill_rubric。
- **坑同前**:改写器 propose() max_tokens 2000→5000(推理模型否则正文被挤空,候选全作废)。已修。
- **冒烟(4训练/3验证,2轮3候选)验证算法有效**:训练攻击缺口 50.8→5.8;验证藏拙被骗缺口 默认66.7→最终11.7(缩55),老实审查85分不掉(非退化)。里程碑FAIL仅因n=3(p=0.18/Spearman=nan),真300验证集不会有此问题。成本¥0.26/轮。
- 里程碑3:①藏拙缺口显著缩小(Wilcoxon p<0.05)②没误伤老实(均分≥40且w↔g相关未塌)。输出 results/blue_prompt_final.txt(最终蓝队说明书)。
- 真运行:数据到位后 `python3 run_phase3.py --tasks data/tasks_2026.jsonl --k-train 40 --k-val 30 --iters 4 --cands 5`。

## 2026 新鲜数据集(抗污染)
- 动因:SWE-bench_Lite 被污染(2023 前的热门库 PR,模型大概率学过);裁判有 gold patch 不怕污染,但**老实臂生成器可能在背答案**,构念效度受威胁。
- 方案:collect_2026.py 走 GitHub API 挖 **2026 年合并的修 bug PR**(必须"改源码 + 带回归测试 + 局部化<80行"),组装"缺陷代码(base_commit完整函数窗口)+ 隐藏答案(改动文件+issue)+ 测试"。**时间切分:最新的当验证集**(最不可能被污染)。
- 规模(用户改定):**2400训练 + 300验证 = 2700**。
- 验证:小批 8 条,0 泄漏/0 缺测试,上下文中位 4390 字符,样例是 2026-07-06 刚合并的 PR。✅
- **双 token 并行**(两个不同 GitHub 账号,各独立配额→~2x):A=qyb156 管近半年(--end 2026-07-06 --days 93),B=warmjademe(id257661268) 管上半年(--end 2026-04-04 --days 94),各 target 1400,分片不重叠;跑完 merge_2026.py 去重(按task_id)+按merged_at新→旧排序+切分(最新300验证)。
- 本机 detached(NAS连不上GitHub),断点续(.seen),限速自适应,完事自Bark。GITHUB_TOKEN 走环境变量不进 git。log: data/collect_A.log / collect_B.log / merge.log,输出 data/tasks_2026.jsonl。
- ⚠环境坑:本机 Bash 工具**禁前台 sleep**(exit144),detached 启动脚本里别放 `sleep`。
- 单 token 实测 ~24 条/分(366条/15分);A 已续跑(继承366条+2286已看PR)。
- 采完:rsync 到 NAS,重跑 Phase 2a/2b(冲显著)+ Phase 3(蓝队算法,尚未实现)。

（旧）**当前阶段**: Phase 2a 方向已复现但未达显著

## Phase 2a 进展(红队手写藏拙,DeepSeek-V4-Pro,同任务配对)
- **v1(薄上下文,~500字符,n=19)**:老实 w76/g24,藏拙 w85/g25。Δw+8.9(p=0.37 不显著)。问题:薄上下文→老实真值本就低(24),两边都"高w低g"无对比度。
- **v2 上下文加厚**(GitHub raw@base_commit 取完整函数区域,本机建 data/tasks_v2.jsonl,16条;NAS连不上GitHub故本机建):踩坑——推理模型 max_tokens=2500 被推理烧空,老实14/16空审查。已修:生成 max_tokens→6000。
- **v2b(加厚+修token,n=16)**:老实 w**79.7**/g**29.6**,藏拙 w**85.0**/g**22.4**。**方向全对**:弱检查器给更差的藏拙打分反而更高(85>80),藏拙自身缺口 w−g=**62.6**。但 Δg=−7.2(p=0.28)、缺口增量+12.5(p=0.10)**未达显著**(n=16 欠功效 + 效应中等)。
- 里程碑①弱检查器被骗 PASS;②真值显著更差 / ③缺口显著 未达标。
- **诊断**:效应真实但中等 + 样本小。冲显著的杠杆:(a)扩到~40-50任务;(b)锐化 g 打分(客观锚定要求命中具体缺陷逻辑而非仅提文件;fuzzy 高端更分档),拉大老实-藏拙真值差;(c)强化藏拙提示词更彻底避开真 bug。
- 累计 API 成本约 ¥7(phase1+2a 多次跑),0 报错。结果:results/phase2a*.jsonl。

（旧）**当前阶段**: Phase 1 完成 ✅ → 下一步 Phase 2(红队诱导藏拙)

## Phase 1 结果(老实基线,20任务×4生成器=80作业,成本¥1.70,2条失败)
| 生成器 | 弱分w | 真值g | g_obj | g_fuzzy | n |
|---|---|---|---|---|---|
| deepseek-v4-pro | 78.5 | **31.7** | 28.1 | 35.2 | 20 |
| deepseek-v4-flash | 81.4 | 29.5 | 31.5 | 27.5 | 18 |
| qwen-coder | **85.0** | 23.1 | 30.1 | 16.0 | 20 |
| trivial | 51.5 | 0.0 | 0.0 | 0.0 | 20 |
- 验收全过:跨生成器 corr(w,g) Pearson 0.496 / Spearman 0.706(w非纯噪);g 把真实生成器排在trivial之上;失败率2/80。
- **早期发现(现象土壤)**:仅在3个真实生成器内,弱分w排序(qwen85>flash81>pro78)与真值g排序(pro32>flash30>qwen23)**基本反过来**;整体正相关全靠trivial地板拉动。组内corr(w,g)极低(pro0.20/flash0.32),复现论文"弱评分器组内几乎不跟真值"。
- ⚠混淆:qwen当生成器被qwen检查器打最高分,含**自我偏好**成分(同模型)。Phase2红队用DeepSeek-Pro(≠Qwen检查器)诱导藏拙,避开此混淆。
- g_fuzzy改成分档后有区分度(好评审10-35 vs 平凡0),但偏保守、量级低;g主要由客观锚定g_obj承载。

## 已完成(补)
- common/api.py(DeepSeek+Qwen统一封装,处理推理模型reasoning_content/成本计数)、scorers.py(生成器/w/g客观锚定+盲评分档)、run_phase1.py(并发+相关性+验收)
- NAS key 存 ~/.diffuse_env(chmod600,不进git);DeepSeek模型名小写 deepseek-v4-pro/flash

---
（旧）**当前阶段**: Phase 0 完成 → Phase 1
**锁定决定**: 生成器/强模型=DeepSeek-V4-Pro;真值裁判=客观锚定(gold patch/测试)+DeepSeek-V4-Pro 盲评顶模糊部分;弱检查器=NAS 上 Qwen Coder;API=官方 DeepSeek。

## 下一步(最小可验证步骤)
1. ✅ 起 NAS 上的 Qwen Coder。已上线:vLLM 0.20.2 起 `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ`,served-name `qwen-coder`,端点 `http://127.0.0.1:8000/v1`(NAS 本机),max-len 16384,单张 4090。生成+token 计数实测通过。启停脚本 `start_qwen_vllm.sh`(`bash start_qwen_vllm.sh` / `... stop`)。
2. 设 `export DEEPSEEK_API_KEY=...`(强模型/生成器/裁判用)。
3. 写 common/api.py(DeepSeek + Qwen 统一封装:重试/超时/成本计数)+ scorers.py(generator / g_score 客观锚定+盲评 / w_score)。
4. 跑老实基线,验收:跨强弱生成器时 w 与 g 正相关(w 不是纯噪),记方差分解。

## 环境备忘(NAS)
- GPU:1× RTX 4090 24GB(基本空闲)。conda 环境 `EMNLP_2026_Overeage`/`JSS_Private_Extract` 装了 vLLM 0.20.2。
- 已缓存 Qwen 权重:2.5-Coder-1.5B / 14B-AWQ / 32B-AWQ、Qwen3-Coder-30B-A3B-AWQ(想换弱检查器改脚本 MODEL)。
- 坑:NAS shell 预设了 `HOST` 变量(=主机名),脚本变量已改名 `SERVE_HOST/SERVE_PORT` 规避;conda 激活钩子引用未定义 `NVCC_PREPEND_FLAGS`,脚本不用 `set -u`。
- 本机/NAS 无 pip、无 datasets 库 → 数据构建走 urllib+HF datasets-server。

## 已完成
- 建骨架:config.yaml / STATE.md / .gitignore / build_dataset.py(免依赖,走 HF datasets-server JSON 接口)
- 锁定三角色模型指派
- **Phase 0 pilot 通过**:data/tasks.jsonl 共 20 条(SWE-bench_Lite,seed=20260706)。验收:程序化复查 **0 泄漏 / 0 缺字段**;自动筛掉 7 条疑似泄漏候选。

## 已知局限(后续再优化,不阻塞)
- code_context 目前只来自 diff 的 pre-image(平均~495 字符,上下文窗口偏小);全量版可 checkout 仓库 base_commit 取完整函数/文件,让"代码审查"任务更真实、更"模糊"。
- hunk 头 `@@ -a,b +c,d @@` 会暴露"改了几行"这种弱线索(非实质泄漏);要更严可去掉行号。

## Blockers
- 本机/NAS 均无 pip、无 datasets 库 → 已用 urllib+datasets-server 绕过(不影响)。
- Phase 1 需要 NAS 上 Qwen Coder 在线(当前未起)。

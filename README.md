# 言屿 · 语料分布校对室

冻结参考分箱，把候选语料的变化读到具体切片，再形成有依据的补采说明。

言屿字幕语料组有20位数据研究与采集人员。现有流程把训练与新增采集的元特征粘到表格，分别重画直方图、逐项看p值，再凭总体均值讨论补采；三个痛点是候选重分箱使两边无法比较、多重检验产生误报、分布变化被直接写成模型质量下降。这里承接“匿名片段元特征→冻结参考箱/差异与FDR核对→补采计划→负责人审稿→CSV交付”。不处理字幕正文，也不直接评估下游模型质量。

## 快速启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [校对室](http://localhost:18215)，[后端文档](http://localhost:19215/docs)，MySQL映射17715。首次API启动自动seed；失败记录日志而不阻塞API，可单独运行脚本。初始2个快照各900片段，共1800；5个特征、1份Python真算比较、5个持久化发现、1份补采草案。固定种子113，参考与候选分别为 `yy-corpus-202611-reference.csv` 和 `yy-corpus-202611-candidate.csv`。

| 账号 | 密码 | 权限 |
|---|---|---|
| admin@yanyu.demo | Yanyu2026! | admin语料负责人：阅读、导入、比较、建立计划、审核；仅获批计划可导出 |
| analyst@yanyu.demo | Yanyu2026! | analyst分布研究员：阅读、导入、比较、建立计划；审核返回403；仅获批计划可导出 |
| viewer@yanyu.demo | Yanyu2026! | viewer采集观察员：只读、获批CSV下载；写入均403 |

## 一天的校对剧本

1. 09:00 梁栩以analyst登录，检查参考/候选各900条元特征。
2. 在语料快照中读前100条样本，看到duration/noise/token_rate和language/device；null明确显示为缺失。
3. 建立“十一月采集分布复校”，选择五特征，参考分位箱6、每桶平滑伪计数0.5、FDR α=.05。
4. 先做全量比较，再可按语言zh/设备mobile过滤两边；任一切片不足5条会明确failed，不静默当无漂移。
5. worker只用参考非缺失值拟合分位边界与参考类别字典，再将候选投影到冻结箱。
6. 看PSI/JS效应量、连续KS原p/BH q及FDR拒绝；打开language看到__NEW__和__MISSING__独立计数。
7. 从当前发现建立“来源结构补采说明”，填写切片、目标200片段和采集理由。
8. 叶砚以admin审稿，说明先核对来源再补采，后续质量变化须独立评测。
9. 唐禾以viewer导出获批CSV，保留发现指标、校正q与审稿说明；不将漂移直接表述为质量劣化。

## 数据、分箱与统计口径

五个核心实体CorpusSnapshot、Utterance、ComparisonRun、DriftFinding、ResamplingPlan，均贯穿表/model/schema/service/route/API/store/UI。六页为校对首页、语料快照、比较配置、漂移发现、补采审稿、校对留痕；HistogramBins、FindingSummary、RunTable跨页复用，同时共享Table/Badge/Notice/Empty。

数值特征：duration（秒）、noise（dB）、token_rate（token/s）；类别：language、device。API导入20–5000条JSON数组，每项reference唯一、五特征完整，值可null；数值必须有限，类别必须非空字符串，保留名__NEW__/__MISSING__禁止作为真实类别。没有CSV解析器或真实采集接口。

`services/binning.py`：只对参考快照在当前切片的非缺失连续值拟合等频分位内边界，`np.quantile`内点去重，尾箱延伸±∞。重复边界会减少实际箱数。`searchsorted(side='right')`使区间左闭右开，正好等于边界进入右箱；候选极值只进入尾箱，绝不改变边界。null单列__MISSING__。参考数值少于2有效值或常量明确失败，不伪造分箱。参考类别字典冻结为排序后的非缺失类别，候选未见类别合入__NEW__，null另入__MISSING__；参考全缺失类别失败。候选常量数值允许比较，候选连续有效值不足2则无法KS而失败。

`services/distributions.py`：设每桶计数a_i/b_i、总量N/M、桶数K，伪计数α>0：p_i=(a_i+α)/(N+Kα)，q_i=(b_i+α)/(M+Kα)。每桶都平滑，包含新类别与缺失空桶。PSI=Σ(q_i−p_i)ln(q_i/p_i)，使用自然对数；JS=.5Σp_i log₂(p_i/m_i)+.5Σq_i log₂(q_i/m_i)，m=(p+q)/2，单位bit，JS在0至1。固定同一箱字典时交换p/q对称；交换整条管线的参考/候选会重建分箱，不能假定得到相同数值。缺失桶参与散度，缺失比例另报。

`services/comparison.py`：所选连续特征的非缺失值执行双侧两样本KS（SciPy ks_2samp，method=auto），统计量是两ECDF最大绝对差。类别不执行KS，p/q为null。`services/multiple_testing.py`对本运行全部所选连续特征组成的一个检验族做Benjamini–Hochberg：排序p_(i)，q_(i)=min_{j≥i}(m p_(j)/j,1)，再映回原顺序；q≤配置FDR α才标记拒绝。默认五特征中m=3，而不是把类别也算入m。BH的FDR解释有独立或适当正相关依赖等条件；这里没有证明真实语料任意依赖条件下的FDR控制。

“建议核对”取 q≤FDRα 或 PSI≥.2 或 JS≥.05，后两者是明确的效应量启发阈值，不是p值或显著性。页面分别显示FDR拒绝和建议核对，未拒绝也不声称分布相同。分布漂移不能证明下游模型变差，补采应先调查采样口径与来源，并独立评估质量。

计算失败态包括空快照、空/不足5条的切片、参考连续常量/全缺失、连续有效值不足、非有限值、未知/重复特征及非法平滑/FDR/分箱参数。结果存完整冻结箱、两边计数/平滑比例、原p/q/检验族、参考/候选切片ID和输入SHA-256。指纹覆盖两边全量id/reference/全部五特征（包含null及未选特征）、配置和算法版本，按reference稳定排序；顺序改变不改指纹，任一影响字段变化会改指纹。

## 离线批量校对

`backend/src/batch.py` 提供不依赖 MySQL/Redis 的批量入口，逐项仍调用同一个 `services.comparison.compare_snapshots`，所以冻结参考箱、伪计数、PSI/JS、KS 与 BH 口径与页面完全一致。

```sh
# 从仓库根目录；也可 cd backend 后 python -m src.batch 或 python scripts/batch_compare.py
python backend/scripts/batch_compare.py manifest.json --output-dir batch-results
```

清单为 JSON：`items` 每项给出 `id`、`reference`、`candidate` 与 `config`（内联对象或 JSON 文件路径）；路径相对清单目录。可用 `snapshots`/`configs` 名称别名，`defaults` 提供默认快照、配置，快照也可内联为片段数组或 `{"utterances":[...]}` 对象。

```json
{"items":[{"id":"nov-full","reference":"ref.json","candidate":"cand.json","config":"full.json"}]}
```

配置字段沿用 API：`features`、`bins`、`smoothing`、`fdr_alpha`、`slice_language`、`slice_device`；缺省为五特征、6箱、0.5、0.05、全量切片。

结果目录在 `items/` 下按 item id 保存逐项记录（含完整 findings），在 `cache/` 下保存按输入哈希寻址的成功结果，并写入 `summary.json`。每项独立执行：单项读文件/校验/计算/写盘失败只记该 `failed`，其余继续，进程退出码为 1；清单本身不可用退出 2；中断退出 130。成功结果写入前校验完整性（`status=succeeded`、`complete=true`、输入/比较指纹、配置、findings 数与指标），再用临时文件 `fsync` + 原子替换，半写文件不会被当作成功。再次运行按“全量输入 + 比较配置 + 算法/结果版本”的哈希复用成功项，只重算源数据或规则变化的项；同输入跨清单项也可共享缓存。失败项不缓存，修复后直接补跑。`--force` 忽略缓存全部重算，`--quiet` 关闭 stderr 逐项进度；机器可读汇总同时打印到 stdout 并原子写入 `summary.json`。

## 工程与开发

| 层 | 实现 |
|---|---|
| 前端 | Vue3.5.45 / TypeScript5.7 / vue-tsc3.3 / Vite6.4.6 / Nginx1.27 |
| 后端 | Python3.11 / FastAPI / SQLAlchemy2 / Pydantic |
| 算法 | NumPy2.2.1、SciPy1.15 |
| 数据/任务 | MySQL8 / Redis7 / Celery5.4 + Kombu5.4.2 |
| 认证 | PBKDF2-SHA256 210000轮、JWT HS256 8小时、服务器角色校验 |

五服务恰为frontend/backend/worker/db/redis，全部有健康探针/健康依赖；Nginx探针127.0.0.1，worker定向Celery ping。db-data、redis-data、artifacts分别持久化库、队列、共享计算JSON。Nginx剥离/api/前缀，API原生路由无重复前缀。Kombu锁定5.4.2，避免Celery5.4 Redis extra与新Kombu redis-py范围冲突。

环境变量见.env.example：COMPOSE_PROJECT_NAME隔离短名；FRONTEND_PORT/BACKEND_PORT/DB_PORT映射；MYSQL_DATABASE/USER/PASSWORD及ROOT_PASSWORD配置库；JWT_SECRET签名；SEED_DEMO控制自动种子。演示值用于本机，部署通过环境变量替换。

```sh
# 本机设置可达 DATABASE_URL / REDIS_URL / JWT_SECRET
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 19215
# 另一个终端，同环境变量
celery -A src.worker.app worker --concurrency=1
# 前端Vite开发代理已指向127.0.0.1:19215
cd frontend
npm ci
npm run dev
```

结构：backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}；backend/scripts/seed_demo.py；backend/migrations/；frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。metadata首次建表，migrations说明结构，生产增量升级需另行规划。快照名/片段自然键/基准运行名让seed可重复且不覆盖用户修改；基准仅缺失时计算。请求ID和全局错误两个中间件；AuditLog记录登录、导入、任务和审稿；CSV公式前缀转义。

共享枚举位置：后端backend/src/constants/enums.py的Role/RunStatus/PlanStatus/FindingStatus；前端frontend/src/constants/enums.ts对应角色/运行/计划/发现标签；使用于鉴权、运行/计划服务、schema和Badge/Layout/各页面。测试脚本、真实截图、CSV、日志、报告仅位于批次根test-artifacts/gb-0011，源码不含截图/测试报告。真机测试、oracle和已知差异见该目录TESTING.md。

## 范围与License

合成匿名片段仅展示分布研究，不含真实字幕、说话人或设备身份；没有下游模型质量评测、生产负载验证或自动补采执行。页面样本前100条、完整切片用于计算；获批计划CSV供人工采集安排。Google字体联网加载，离线使用浏览器回退。收尾 `docker compose down -v --remove-orphans` 清理本栈演示卷。

MIT，见LICENSE。

# 依赖安装 403 与 smoke check 失败排查（中文）

## 结论
当日志出现以下两条时，说明**本次运行未成功完成**：

- `pip install -r requirements.txt` 无法访问包索引（`Tunnel connection failed: 403 Forbidden`）。
- 后续 Python smoke check 因缺少 `pandas` 等依赖而未执行。

这属于**环境网络限制**，不是业务代码逻辑报错。

## 建议优化（按优先级）

### 1) 为 pip 显式配置可访问镜像（推荐）
一次性命令：

```bash
python -m pip install -q -r requirements.txt \
  -i https://pypi.org/simple \
  --trusted-host pypi.org \
  --trusted-host files.pythonhosted.org
```

若你所在网络对 `pypi.org` 不通，改为企业内网镜像或团队镜像：

```bash
python -m pip install -q -r requirements.txt -i <your-mirror-url>
```

### 2) 增加安装重试与超时容错

```bash
python -m pip install -q -r requirements.txt \
  --retries 5 --timeout 60
```

### 3) 先做“依赖可用性探测”再跑 smoke check
可先执行：

```bash
python - <<'PY'
import importlib
mods = ["pandas"]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
print("MISSING:", missing)
raise SystemExit(1 if missing else 0)
PY
```

若输出 `MISSING: ['pandas']`，说明应该先解决安装问题，而不是直接跑业务 smoke check。

### 4) 在 CI/脚本中区分“环境失败”与“代码失败”
建议把日志分类成：
- `ENV_BLOCKED`：网络/权限导致依赖安装失败。
- `TEST_FAILED`：依赖齐全但测试失败。

这样可以避免把环境问题误判成代码回归。

## 建议的执行顺序
1. 配置可访问镜像并安装依赖。
2. 验证 `pandas` 可导入。
3. 再运行 smoke check。
4. 若仍失败，再定位业务逻辑。


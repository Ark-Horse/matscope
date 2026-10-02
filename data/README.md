# 数据来源与含义

`processed/` 包含由 matminer 的 `elastic_tensor_2015` 数据集提取的 1,181 条记录及结构，以及本平台计算的 120 条模拟 XRD 谱。全部记录成功解析，没有用合成性质补齐标签。

原始出处：de Jong et al. **Charting the complete elastic properties of inorganic crystalline compounds**. *Scientific Data* 2, 150009 (2015). [DOI: 10.1038/sdata.2015.9](https://doi.org/10.1038/sdata.2015.9)。

- [matminer 官方数据说明](https://hackingmaterials.lbl.gov/matminer/dataset_summary.html#elastic-tensor-2015)
- [官方元信息](https://github.com/hackingmaterials/matminer/blob/main/src/matminer/datasets/dataset_metadata.json)
- 下载入口：`https://ndownloader.figshare.com/files/13220603`
- 同一文件的存储入口：`https://s3-eu-west-1.amazonaws.com/pfigshare-u-files/13220603/elastic_tensor_2015.json.gz`
- 原文件 SHA256：`8c3b342f75da7e7baa1b769b59554485fd647f4cb1da9318d0d1ba3b3b838183`

原始计算数据在原文 Data Records / Usage Notes 中说明为公开数据；引用原论文与 Materials Project 数据来源。仓库 MIT 许可仅用于原创代码，不覆盖上游数据。`provenance.json` 保存机器可读来源与校验值。科学数据库内容的再使用应遵守原始发布条款。

| 文件 | 内容 |
| --- | --- |
| catalog.json | 材料标识、成分、密度、对称性、弹性性质 |
| structures.json | 按材料 ID 关联的 pymatgen 结构对象 |
| xrd_library.json | 结构正向计算的模拟峰，Cu Kα₁ 1.5406 Å |
| model_report.json | 独立测试集指标、预测对照、全局特征重要性 |
| split.json | 固定随机种子 42、按约化化学式分组的训练/测试 ID |
| provenance.json | 数据出处、校验值、模拟条件与保留记录数 |

弹性性质是 **DFT-PBE 计算参考值**，不是实验测量值。密度与几何描述由对应晶体结构计算。没有按化学式拼接不同晶型的标签。

`examples/silicon.cif` 导出自数据集中硅结构。`examples/silicon_simulated_noisy.csv` 为结构模拟谱加入固定种子的高斯噪声与常量基线得到的演示数据，**不是实验谱图**。

重建数据：`uv run python scripts/prepare_data.py`。默认使用上述下载入口，失败时使用同文件存储入口；校验通过后才解析。默认运行服务只读取已准备数据，不访问远程材料数据库。

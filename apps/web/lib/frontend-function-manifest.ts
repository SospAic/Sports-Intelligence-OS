export type FrontendCoverageTier = "smoke" | "interaction" | "workflow";

export type FrontendFunctionManifestEntry = {
  route: string;
  tier: FrontendCoverageTier;
  criticalActions: string[];
};

/**
 * Route-level acceptance inventory. The companion test compares this list
 * with every Next.js page file so a newly added page cannot silently skip the
 * frontend test plan.
 */
export const FRONTEND_FUNCTION_MANIFEST: FrontendFunctionManifestEntry[] = [
  { route: "/", tier: "smoke", criticalActions: ["登录入口", "首屏渲染"] },
  { route: "/login", tier: "workflow", criticalActions: ["登录", "错误提示", "跳转工作台"] },
  { route: "/dashboard", tier: "workflow", criticalActions: ["指标加载", "时间范围", "快捷入口"] },
  { route: "/accounts", tier: "workflow", criticalActions: ["筛选", "排序分页", "同步账号", "进入详情"] },
  { route: "/accounts/[id]", tier: "workflow", criticalActions: ["概览", "作品/趋势", "同步记录", "取消任务"] },
  { route: "/accounts/[id]/sync-runs/[runId]", tier: "interaction", criticalActions: ["运行详情", "阶段日志", "错误状态"] },
  { route: "/accounts/compare", tier: "workflow", criticalActions: ["选择账号", "指标切换", "时间范围", "导出/空态"] },
  { route: "/contents", tier: "workflow", criticalActions: ["筛选排序", "批量操作", "列表/日历", "分页"] },
  { route: "/contents/[id]", tier: "workflow", criticalActions: ["媒体预览", "字幕", "热门评论", "下载设置"] },
  { route: "/trends", tier: "workflow", criticalActions: ["开始采集", "实时状态", "筛选", "去重榜单"] },
  { route: "/trends/analytics", tier: "workflow", criticalActions: ["榜单", "趋势图", "同题机会", "指标解释"] },
  { route: "/video-search", tier: "workflow", criticalActions: ["创建搜索", "结果筛选", "证据定位", "加入选题"] },
  { route: "/news", tier: "workflow", criticalActions: ["筛选", "分页", "详情跳转", "来源状态"] },
  { route: "/news/[id]", tier: "interaction", criticalActions: ["来源证据", "时间字段", "关联事件", "返回列表"] },
  { route: "/events", tier: "workflow", criticalActions: ["事件列表", "聚类筛选", "时间线", "详情跳转"] },
  { route: "/events/[id]", tier: "interaction", criticalActions: ["事件时间线", "来源", "关联内容", "空态"] },
  { route: "/topics", tier: "workflow", criticalActions: ["创建选题", "筛选", "状态变更", "详情/删除边界"] },
  { route: "/generate", tier: "workflow", criticalActions: ["选择素材", "规则输入", "生成提交", "失败/进度"] },
  { route: "/generations", tier: "interaction", criticalActions: ["运行列表", "状态筛选", "分页", "详情跳转"] },
  { route: "/generations/[id]", tier: "workflow", criticalActions: ["步骤进度", "证据包", "QA/重写", "采用"] },
  { route: "/editorial", tier: "workflow", criticalActions: ["审核队列", "评论处理", "状态变更", "SLA"] },
  { route: "/publications", tier: "interaction", criticalActions: ["发布记录", "账号范围", "状态/权限边界"] },
  { route: "/rules", tier: "workflow", criticalActions: ["集合列表", "版本状态", "导入入口", "权限"] },
  { route: "/rules/import", tier: "workflow", criticalActions: ["TXT/JSON 导入", "预览校验", "冲突错误", "提交"] },
  { route: "/rules/[ruleSetId]", tier: "interaction", criticalActions: ["规则树", "版本切换", "发布/回滚", "导出"] },
  { route: "/rules/[ruleSetId]/edit", tier: "workflow", criticalActions: ["结构化编辑", "字段校验", "草稿保存", "冲突提示"] },
  { route: "/rules/[ruleSetId]/compare", tier: "interaction", criticalActions: ["版本选择", "差异展示", "空态"] },
  { route: "/rules/[ruleSetId]/versions/[versionId]", tier: "interaction", criticalActions: ["版本详情", "模拟", "历史反馈"] },
  { route: "/prompts", tier: "interaction", criticalActions: ["列表", "发布状态", "版本跳转"] },
  { route: "/prompts/[id]", tier: "workflow", criticalActions: ["编辑变量", "预览脱敏", "发布/回滚"] },
  { route: "/workflows", tier: "smoke", criticalActions: ["工作流步骤", "版本读取", "只读说明"] },
  { route: "/automations", tier: "workflow", criticalActions: ["筛选", "启停", "编辑入口", "执行状态"] },
  { route: "/automations/new", tier: "workflow", criticalActions: ["条件树", "动作配置", "校验", "保存"] },
  { route: "/automations/[id]", tier: "workflow", criticalActions: ["编辑", "求值/回放", "运行历史", "删除边界"] },
  { route: "/notification-channels", tier: "workflow", criticalActions: ["新建渠道", "敏感字段", "测试回执", "启停"] },
  { route: "/notification-templates", tier: "interaction", criticalActions: ["模板列表", "预览", "版本/空态"] },
  { route: "/notifications", tier: "interaction", criticalActions: ["通知列表", "未读/已读", "筛选", "历史跳转"] },
  { route: "/operations/external-calls", tier: "interaction", criticalActions: ["调用记录", "失败详情", "脱敏"] },
  { route: "/operations/dead-letters", tier: "workflow", criticalActions: ["死信筛选", "重放", "丢弃确认", "权限"] },
  { route: "/operations/experiments", tier: "workflow", criticalActions: ["实验创建", "变体", "观察性报告", "非因果声明"] },
  { route: "/operations/rights", tier: "workflow", criticalActions: ["权利状态", "证据", "保留期", "权限"] },
  { route: "/operations/slo", tier: "interaction", criticalActions: ["SLO 指标", "窗口", "空数据边界"] },
  { route: "/tasks", tier: "workflow", criticalActions: ["任务筛选", "日志", "取消/重试", "失败态"] },
  { route: "/logs", tier: "interaction", criticalActions: ["事件筛选", "详情", "分页", "脱敏"] },
  { route: "/download", tier: "workflow", criticalActions: ["URL 解析", "运行时检查", "预览", "下载设置"] },
  { route: "/settings", tier: "workflow", criticalActions: ["配置检查", "平台探针", "LLM 测试", "通知/存储/索引"] },
];

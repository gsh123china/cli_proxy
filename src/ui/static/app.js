// Vue 3 + Element Plus CLI Proxy Monitor Application
const { createApp, ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } = Vue;
const { ElMessage, ElMessageBox } = ElementPlus;

const app = createApp({
    setup() {
        // 响应式数据
        const loading = ref(false);
        const logsLoading = ref(false);
        const allLogsLoading = ref(false);
        const configSaving = ref(false);
        const filterSaving = ref(false);
        const headerFilterSaving = ref(false);       // Header Filter saving state（新增）
        const lastUpdate = ref('加载中...');
        
        // 自动刷新相关
        const AUTO_REFRESH_INTERVAL = 300;      // 自动刷新间隔（秒，5分钟 = 300秒）
        const autoRefreshCountdown = ref(AUTO_REFRESH_INTERVAL);  // 倒计时秒数，初始值为刷新间隔
        const autoRefreshTimer = ref(null);     // setInterval 定时器引用
        
        // 服务状态数据
        const services = reactive({
            claude: {
                running: false,
                pid: null,
                config: ''
            },
            codex: {
                running: false,
                pid: null,
                config: ''
            }
        });
        
        // 统计数据
        const stats = reactive({
            requestCount: 0,
            configCount: 0,
            filterCount: 0,
            headerFilterCount: 0,      // Header Filter 数量
            endpointFilterCount: 0     // Endpoint Filter 数量（新增）
        });
        
        // 日志数据
        const logs = ref([]);
        const allLogs = ref([]);
        
        // 配置选项
        const claudeConfigs = ref([]);
        const codexConfigs = ref([]);
        const configMetadata = reactive({
            claude: {},
            codex: {}
        });
        
        // 抽屉状态
        const configDrawerVisible = ref(false);
        const bodyFilterDrawerVisible = ref(false);      // Body Filter（原 filterDrawerVisible）
        const headerFilterDrawerVisible = ref(false);    // Header Filter（新增）
        const endpointFilterDrawerVisible = ref(false);  // Endpoint Filter（新增）
        const logDetailVisible = ref(false);
        const allLogsVisible = ref(false);
        const logDetailLoading = ref(false);
        const logDetailError = ref(null);
        const logDetailRequestId = ref(null);
        const activeConfigTab = ref('claude');
        const activeLogTab = ref('basic'); // 日志详情Tab状态
        
        // 配置内容
        const configContents = reactive({
            claude: '',
            codex: ''
        });
        const filterContent = ref('');
        const filterRules = ref([]);  // 过滤规则数组

        // Header Filter 配置（新增）
        const headerFilterConfig = reactive({
            enabled: true,
            blocked_headers: []
        });

        // Endpoint Filter 配置（新增）
        const endpointFilterConfig = reactive({
            enabled: true,
            rules: [] // [{ id, services:[], methods:[], matchType:'path'|'prefix'|'regex', matchValue:'', queryPairs:[{key,value}], action:{status,message} }]
        });

        // 友好表单的配置数据
        const friendlyConfigs = reactive({
            // 结构：{ name, baseUrl, authType, authValue, active, weight, deleted, deletedAt }
            claude: [],
            codex: []
        });

        // 配置编辑模式 'interactive' | 'json'
        const configEditMode = ref('interactive');


        // 新增站点编辑状态
        const editingNewSite = reactive({
            claude: false,
            codex: false
        });

        // 新站点数据
        const newSiteData = reactive({
            claude: {
                name: '',
                baseUrl: 'https://',
                authType: 'auth_token',
                authValue: '',
                active: false,
                weight: 0,
                deleted: false,
                deletedAt: null
            },
            codex: {
                name: '',
                baseUrl: 'https://',
                authType: 'auth_token',
                authValue: '',
                active: false,
                weight: 0,
                deleted: false,
                deletedAt: null
            }
        });

        // 测试功能相关数据
        const modelSelectorVisible = ref(false);
        const testResultVisible = ref(false);
        const testingConnection = ref(false);
        const testConfig = reactive({
            service: '',
            siteData: null,
            isNewSite: false,
            siteIndex: -1,
            model: '',
            reasoningEffort: ''
        });
        const lastTestResult = reactive({
            success: false,
            status_code: null,
            response_text: '',
            target_url: '',
            error_message: null
        });

        // 新站点测试结果
        const newSiteTestResult = reactive({
            claude: null,
            codex: null
        });

        // 测试响应数据弹窗
        const testResponseDialogVisible = ref(false);
        const testResponseData = ref('');

        // 同步状态控制，防止循环调用
        const syncInProgress = ref(false);
        const selectedLog = ref(null);
        const decodedRequestBody = ref(''); // 解码后的请求体（转换后）
        const decodedOriginalRequestBody = ref(''); // 解码后的原始请求体
        const decodedResponseContent = ref(''); // 解码后的响应内容

        // 实时请求相关数据
        const realtimeRequests = ref([]);
        const realtimeDetailVisible = ref(false);
        const selectedRealtimeRequest = ref(null);
        const connectionStatus = reactive({ claude: false, codex: false });
        const realtimeManager = ref(null);
        const maxRealtimeRequests = 20;

        // 模型路由管理相关数据
        const routingMode = ref('default'); // 'default' | 'model-mapping' | 'config-mapping'
        const modelMappingDrawerVisible = ref(false);
        const configMappingDrawerVisible = ref(false);
        const activeModelMappingTab = ref('claude'); // 默认选中claude
        const activeConfigMappingTab = ref('claude'); // 默认选中claude
        const routingConfig = reactive({
            mode: 'default',
            modelMappings: {
                claude: [],  // [{ source: 'sonnet4', target: 'opus4' }]
                codex: []
            },
            configMappings: {
                claude: [],  // [{ model: 'sonnet4', config: 'config_a' }]
                codex: []
            }
        });
        const routingConfigSaving = ref(false);

        // 负载均衡相关数据
        const loadbalanceConfig = reactive({
            mode: 'active-first',
            services: {
                claude: {
                    failureThreshold: 3,
                    currentFailures: {},
                    excludedConfigs: []
                },
                codex: {
                    failureThreshold: 3,
                    currentFailures: {},
                    excludedConfigs: []
                }
            }
        });
        const loadbalanceOptions = reactive({
            autoResetOnAllFailed: true,
            notifyEnabled: true,
            resetCooldownSeconds: 30,
            failureThreshold: 3,
        });
        const loadbalanceSaving = ref(false);
        const loadbalanceLoading = ref(false);
        const resettingFailures = reactive({ claude: false, codex: false });
        const isLoadbalanceWeightMode = computed(() => loadbalanceConfig.mode === 'weight-based');
        const loadbalanceDisabledNotice = computed(() => isLoadbalanceWeightMode.value ? '负载均衡生效中' : '');

        // 请求状态映射
        const REQUEST_STATUS = {
            PENDING: { text: '已请求', type: 'warning' },
            STREAMING: { text: '接收中', type: 'primary' },
            COMPLETED: { text: '已完成', type: 'success' },
            FAILED: { text: '失败', type: 'danger' }
        };

        const metricKeys = ['input', 'cached_create', 'cached_read', 'output', 'reasoning', 'total'];
        const tokenServiceKeys = ['claude', 'codex'];
        const tokenServiceLabels = {
            claude: 'Claude CLI',
            codex: 'Codex CLI'
        };
        const createEmptyMetrics = () => ({
            input: 0,
            cached_create: 0,
            cached_read: 0,
            output: 0,
            reasoning: 0,
            total: 0
        });
        const createEmptyFormatted = () => {
            const formatted = {};
            metricKeys.forEach(key => {
                formatted[key] = '0';
            });
            return formatted;
        };

        const usageSummary = reactive({
            totals: createEmptyMetrics(),
            formattedTotals: createEmptyFormatted(),
            perService: {}
        });
        const usageDrawerVisible = ref(false);
        const usageDetailsLoading = ref(false);
        const usageDetails = reactive({
            totals: {
                metrics: createEmptyMetrics(),
                formatted: createEmptyFormatted()
            },
            services: {},
            tokens: {}
        });
        const usageMetricLabels = {
            input: '输入',
            cached_create: '缓存创建',
            cached_read: '缓存读取',
            output: '输出',
            reasoning: '思考',
            total: '总计'
        };
        
        const normalizeUsageBlock = (block) => {
            const isMetricsMap = block && typeof block === 'object' && !Array.isArray(block) && metricKeys.some(key => key in block);
            const metricsSource = isMetricsMap ? block : (block?.metrics || {});
            const formattedSource = block?.formatted || {};
            const displayMetricsSource = block?.displayMetrics || metricsSource;
            const displayFormattedSource = block?.displayFormatted || formattedSource;

            return {
                metrics: Object.assign(createEmptyMetrics(), metricsSource || {}),
                formatted: Object.assign(createEmptyFormatted(), formattedSource || {}),
                displayMetrics: Object.assign(createEmptyMetrics(), displayMetricsSource || {}),
                displayFormatted: Object.assign(createEmptyFormatted(), displayFormattedSource || {}),
            };
        };

        const resetUsageSummary = () => {
            usageSummary.totals = createEmptyMetrics();
            usageSummary.formattedTotals = createEmptyFormatted();
            usageSummary.perService = {};
        };

        const resetUsageDetails = () => {
            usageDetails.totals = normalizeUsageBlock({});
            usageDetails.services = {};
            usageDetails.tokens = {};
        };

        const formatUsageValue = (value) => {
            const num = Number(value || 0);
            if (!Number.isFinite(num)) {
                return '-';
            }
            const intVal = Math.trunc(num);
            if (intVal >= 1_000_000) {
                const short = Math.floor(intVal / 100_000) / 10;
                return `${intVal} (${short.toFixed(1)}m)`;
            }
            if (intVal >= 1_000) {
                const short = Math.floor(intVal / 100) / 10;
                return `${intVal} (${short.toFixed(1)}k)`;
            }
            return `${intVal}`;
        };

        const getNumeric = (value) => {
            const num = Number(value || 0);
            return Number.isFinite(num) ? num : 0;
        };

        const updateFormattedFromMetrics = (block) => {
            if (!block) {
                return block;
            }
            if (!block.metrics) {
                block.metrics = createEmptyMetrics();
            }
            if (!block.displayMetrics) {
                block.displayMetrics = Object.assign(createEmptyMetrics(), block.metrics);
            }
            if (!block.displayFormatted) {
                block.displayFormatted = createEmptyFormatted();
            }
            metricKeys.forEach(key => {
                block.displayFormatted[key] = formatUsageValue(getNumeric(block.displayMetrics?.[key]));
            });
            block.formatted = block.displayFormatted;
            return block;
        };

        const adjustUsageBlockForService = (service, block) => {
            const normalized = normalizeUsageBlock(block);
            if (!normalized.metrics) {
                return normalized;
            }
            if (service === 'codex') {
                const cachedRead = getNumeric(normalized.metrics.cached_read);
                const adjustedInput = Math.max(0, getNumeric(normalized.metrics.input) - cachedRead);
                const adjustedTotal = Math.max(0, getNumeric(normalized.metrics.total) - cachedRead);
                normalized.displayMetrics.input = adjustedInput;
                normalized.displayMetrics.total = adjustedTotal;
                normalized.displayMetrics.cached_read = getNumeric(normalized.metrics.cached_read);
            } else {
                normalized.displayMetrics = Object.assign(createEmptyMetrics(), normalized.metrics);
            }
            return updateFormattedFromMetrics(normalized);
        };

        const mergeMetricsInto = (target, sourceMetrics) => {
            if (!sourceMetrics) {
                return;
            }
            metricKeys.forEach(key => {
                target[key] = getNumeric(target[key]) + getNumeric(sourceMetrics?.[key]);
            });
        };

        const formatUsageSummary = (usage, serviceOverride = null) => {
            if (!usage || !usage.metrics) {
                return '-';
            }
            const metrics = usage.metrics;
            const service = serviceOverride || usage.service || '';
            const cachedRead = getNumeric(metrics.cached_read);
            const displayInput = service === 'codex'
                ? Math.max(0, getNumeric(metrics.input) - cachedRead)
                : getNumeric(metrics.input);
            const displayTotal = service === 'codex'
                ? Math.max(0, getNumeric(metrics.total) - cachedRead)
                : getNumeric(metrics.total);
            const displayOutput = getNumeric(metrics.output);

            return [
                `IN ${formatUsageValue(displayInput)}`,
                `OUT ${formatUsageValue(displayOutput)}`,
                `Total ${formatUsageValue(displayTotal)}`
            ].join('\n');
        };

        const getUsageFormattedValue = (block, key) => {
            if (!block) return '-';
            const formattedBlock = block.displayFormatted || block.formatted;
            if (formattedBlock && formattedBlock[key]) {
                return formattedBlock[key];
            }
            const metricsSource = block.displayMetrics || block.metrics;
            if (metricsSource) {
                return formatUsageValue(metricsSource[key]);
            }
            return '-';
        };

        const formatChannelName = (name) => {
            if (!name) return '未知';
            return name === 'unknown' ? '未标记' : name;
        };

        const hasUsageData = (block) => {
            if (!block) {
                return false;
            }
            const metricsSource = block.displayMetrics || block.metrics;
            if (!metricsSource) {
                return false;
            }
            return metricKeys.some(key => getNumeric(metricsSource[key]) > 0);
        };

        // 获取模型选项
        const getModelOptions = (service) => {
            if (service === 'claude') {
                return [
                    { label: 'claude-sonnet-4', value: 'claude-sonnet-4-20250514' },
                    { label: 'claude-opus-4', value: 'claude-opus-4-20250514' },
                    { label: 'claude-opus-4-1', value: 'claude-opus-4-1-20250805' }
                ];
            } else if (service === 'codex') {
                return [
                    { label: 'gpt-5-codex', value: 'gpt-5-codex' },
                    { label: 'gpt-5', value: 'gpt-5' }
                ];
            }
            return [];
        };

        // 测试新增站点连接
        const testNewSiteConnection = (service) => {
            const siteData = newSiteData[service];
            if (!siteData.name || !siteData.baseUrl || !siteData.authValue) {
                ElMessage.warning('请先填写完整的站点信息');
                return;
            }
            showModelSelector(service, siteData, true);
        };

        // 测试现有站点连接
        const testSiteConnection = (service, siteIndex) => {
            const siteData = friendlyConfigs[service][siteIndex];
            if (!siteData.name || !siteData.baseUrl || !siteData.authValue) {
                ElMessage.warning('站点信息不完整');
                return;
            }
            showModelSelector(service, siteData, false, siteIndex);
        };

        // 显示模型选择器
        const showModelSelector = (service, siteData, isNewSite = false, siteIndex = -1) => {
            testConfig.service = service;
            testConfig.siteData = siteData;
            testConfig.isNewSite = isNewSite;
            testConfig.siteIndex = siteIndex;
            testConfig.model = '';

            // 重置测试结果
            Object.assign(lastTestResult, {
                success: false,
                status_code: null,
                response_text: '',
                target_url: '',
                error_message: null
            });

            // 设置默认模型
            const options = getModelOptions(service);
            if (options.length > 0) {
                testConfig.model = options[0].value;
            }

            // 设置默认reasoning effort
            if (service === 'codex') {
                testConfig.reasoningEffort = 'high';
            } else {
                testConfig.reasoningEffort = '';
            }

            modelSelectorVisible.value = true;
        };

        // 取消模型选择
        const cancelModelSelection = () => {
            modelSelectorVisible.value = false;
            testConfig.service = '';
            testConfig.siteData = null;
            testConfig.isNewSite = false;
            testConfig.siteIndex = -1;
            testConfig.model = '';
            testConfig.reasoningEffort = '';
        };

        // 确认模型选择并开始测试
        const confirmModelSelection = async () => {
            if (!testConfig.model) {
                ElMessage.warning('请选择要测试的模型');
                return;
            }

            // 重置测试结果
            Object.assign(lastTestResult, {
                success: false,
                status_code: null,
                response_text: '',
                target_url: '',
                error_message: null
            });

            testingConnection.value = true;
            // 不关闭弹窗，在弹窗中显示测试结果

            try {
                const siteData = testConfig.siteData;
                const requestData = {
                    service: testConfig.service,
                    model: testConfig.model,
                    base_url: siteData.baseUrl
                };

                // 根据认证类型设置认证信息
                if (siteData.authType === 'auth_token') {
                    requestData.auth_token = siteData.authValue;
                } else {
                    requestData.api_key = siteData.authValue;
                }

                // 如果是codex且设置了reasoning effort，添加扩展参数
                if (testConfig.service === 'codex' && testConfig.reasoningEffort) {
                    requestData.extra_params = {
                        reasoning_effort: testConfig.reasoningEffort
                    };
                }

                const result = await fetchWithErrorHandling('/api/test-connection', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(requestData)
                });

                // 将测试结果存储到弹窗显示的变量中
                Object.assign(lastTestResult, result);

                // 同时更新对应的测试结果存储位置
                if (testConfig.isNewSite) {
                    // 新站点测试结果
                    newSiteTestResult[testConfig.service] = { ...result };
                } else {
                    // 现有站点测试结果
                    if (friendlyConfigs[testConfig.service] && friendlyConfigs[testConfig.service][testConfig.siteIndex]) {
                        friendlyConfigs[testConfig.service][testConfig.siteIndex].testResult = { ...result };
                    }
                }

                // 不再显示消息提示，结果已在弹窗中显示

            } catch (error) {
                const errorResult = {
                    success: false,
                    status_code: null,
                    response_text: error.message,
                    target_url: '',
                    error_message: error.message
                };

                // 将错误结果存储到弹窗显示的变量中
                Object.assign(lastTestResult, errorResult);

                // 同时更新对应的测试结果存储位置
                if (testConfig.isNewSite) {
                    newSiteTestResult[testConfig.service] = { ...errorResult };
                } else {
                    if (friendlyConfigs[testConfig.service] && friendlyConfigs[testConfig.service][testConfig.siteIndex]) {
                        friendlyConfigs[testConfig.service][testConfig.siteIndex].testResult = { ...errorResult };
                    }
                }
            } finally {
                testingConnection.value = false;
            }
        };

        // 复制测试结果
        const copyTestResult = async () => {
            try {
                await copyToClipboard(lastTestResult.response_text);
            } catch (error) {
                ElMessage.error('复制失败');
            }
        };

        // 显示测试响应数据
        const showTestResponse = (type, service, index = null) => {
            let responseText = '';
            if (type === 'newSite') {
                responseText = newSiteTestResult[service]?.response_text || '';
            } else if (type === 'site' && index !== null) {
                responseText = friendlyConfigs[service][index]?.testResult?.response_text || '';
            }

            if (responseText) {
                testResponseData.value = responseText;
                testResponseDialogVisible.value = true;
            } else {
                ElMessage.warning('没有响应数据');
            }
        };

        // 复制测试响应数据
        const copyTestResponseData = async () => {
            try {
                await copyToClipboard(testResponseData.value);
            } catch (error) {
                ElMessage.error('复制失败');
            }
        };

        // 格式化服务和渠道组合显示（换行形式）
        const formatServiceWithChannel = (service, channel) => {
            const serviceName = service || '-';
            if (!channel || channel === 'unknown') {
                return serviceName;
            }
            return `${serviceName}\n[${channel}]`;
        };

        // 格式化方法和URL的组合
        const formatMethodWithURL = (method, url) => {
            const methodName = method || 'GET';
            const urlPath = url || '-';
            return `[${methodName}] ${urlPath}`;
        };

        const loadUsageDetails = async () => {
            usageDetailsLoading.value = true;
            try {
                const data = await fetchWithErrorHandling('/api/usage/details');
                const services = {};
                const serviceEntries = Object.entries(data.services || {});
                serviceEntries.forEach(([service, payload]) => {
                    const overallBlock = adjustUsageBlockForService(service, payload?.overall || {});
                    const channels = {};
                    Object.entries(payload?.channels || {}).forEach(([channel, channelPayload]) => {
                        if (!channel || channel === 'unknown') {
                            return;
                        }
                        channels[channel] = adjustUsageBlockForService(service, channelPayload || {});
                    });
                    services[service] = {
                        overall: overallBlock,
                        channels
                    };
                });
                usageDetails.services = services;

                const tokenEntries = Object.entries(data.tokens || {});
                const tokens = {};
                tokenEntries.forEach(([tokenName, tokenPayload]) => {
                    const tokenTotals = updateFormattedFromMetrics(normalizeUsageBlock(tokenPayload?.totals || {}));
                const serviceBlocks = {};
                tokenServiceKeys.forEach(service => {
                    const servicePayload = tokenPayload?.services?.[service] || {};
                    const overallBlock = adjustUsageBlockForService(service, servicePayload?.overall || {});
                    const channels = {};
                    Object.entries(servicePayload?.channels || {}).forEach(([channelName, channelPayload]) => {
                        if (!channelName || channelName === 'unknown') {
                            return;
                        }
                        channels[channelName] = adjustUsageBlockForService(service, channelPayload || {});
                    });
                    serviceBlocks[service] = {
                        overall: overallBlock,
                        channels
                    };
                });
                tokens[tokenName] = {
                    totals: tokenTotals,
                    services: serviceBlocks
                };
            });
                usageDetails.tokens = tokens;

                if (serviceEntries.length === 0) {
                    usageDetails.totals = adjustUsageBlockForService('codex', data.totals || {});
                } else {
                    const totalMetrics = createEmptyMetrics();
                    serviceEntries.forEach(([service]) => {
                        mergeMetricsInto(totalMetrics, services[service]?.overall?.displayMetrics || services[service]?.overall?.metrics);
                    });
                    usageDetails.totals = updateFormattedFromMetrics({
                        metrics: Object.assign(createEmptyMetrics(), totalMetrics),
                        displayMetrics: Object.assign(createEmptyMetrics(), totalMetrics),
                        formatted: createEmptyFormatted()
                    });
                }
            } catch (error) {
                resetUsageDetails();
                ElMessage.error('获取Usage详情失败: ' + error.message);
            } finally {
                usageDetailsLoading.value = false;
            }
        };

        const openUsageDrawer = async () => {
            usageDrawerVisible.value = true;
            await loadUsageDetails();
        };

        const closeUsageDrawer = () => {
            usageDrawerVisible.value = false;
        };

        // 清空Token使用数据
        const clearUsageData = async () => {
            try {
                await ElMessageBox.confirm(
                    '确定要清空所有Token使用记录吗？此操作将清空所有日志并重置Token统计数据，不可撤销。',
                    '确认清空Token',
                    {
                        confirmButtonText: '确定',
                        cancelButtonText: '取消',
                        type: 'warning',
                    }
                );

                const result = await fetchWithErrorHandling('/api/usage/clear', {
                    method: 'DELETE'
                });

                if (result.success) {
                    ElMessage.success('Token使用记录已清空');
                    // 刷新页面数据
                    window.location.reload();
                } else {
                    ElMessage.error('清空Token失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                if (error !== 'cancel') {
                    ElMessage.error('清空Token失败: ' + error.message);
                }
            }
        };

        // 模型路由管理方法
        const selectRoutingMode = async (mode) => {
            routingMode.value = mode;
            routingConfig.mode = mode;
            await saveRoutingConfig();
            ElMessage.success(`已切换到${getRoutingModeText(mode)}模式`);
        };

        const getRoutingModeText = (mode) => {
            const modeTexts = {
                'default': '默认路由',
                'model-mapping': '模型→模型映射',
                'config-mapping': '模型→配置映射'
            };
            return modeTexts[mode] || mode;
        };

        const openModelMappingDrawer = () => {
            modelMappingDrawerVisible.value = true;
        };

        const openConfigMappingDrawer = () => {
            configMappingDrawerVisible.value = true;
        };

        const closeModelMappingDrawer = () => {
            modelMappingDrawerVisible.value = false;
        };

        const closeConfigMappingDrawer = () => {
            configMappingDrawerVisible.value = false;
        };

        const addModelMapping = (service) => {
            routingConfig.modelMappings[service].push({
                source: '',
                target: '',
                source_type: 'model'
            });
        };

        const removeModelMapping = (service, index) => {
            routingConfig.modelMappings[service].splice(index, 1);
        };

        const addConfigMapping = (service) => {
            routingConfig.configMappings[service].push({
                model: '',
                config: ''
            });
        };

        const removeConfigMapping = (service, index) => {
            routingConfig.configMappings[service].splice(index, 1);
        };

        const saveRoutingConfig = async () => {
            routingConfigSaving.value = true;
            try {
                const result = await fetchWithErrorHandling('/api/routing/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(routingConfig)
                });

                if (result.success) {
                    ElMessage.success('路由配置保存成功');
                } else {
                    ElMessage.error('路由配置保存失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                ElMessage.error('路由配置保存失败: ' + error.message);
            } finally {
                routingConfigSaving.value = false;
            }
        };

        const loadRoutingConfig = async () => {
            try {
                const data = await fetchWithErrorHandling('/api/routing/config');
                if (data.config) {
                    Object.assign(routingConfig, data.config);
                    routingMode.value = data.config.mode || 'default';

                    // 向后兼容性处理：为没有source_type字段的映射添加默认值
                    ['claude', 'codex'].forEach(service => {
                        if (routingConfig.modelMappings[service]) {
                            routingConfig.modelMappings[service].forEach(mapping => {
                                if (!mapping.source_type) {
                                    mapping.source_type = 'model';
                                }
                            });
                        }
                    });
                }
            } catch (error) {
                console.error('加载路由配置失败:', error);
                // 使用默认配置
                routingMode.value = 'default';
                routingConfig.mode = 'default';
            }
        };

        const getLoadbalanceModeText = (mode) => {
            const mapping = {
                'active-first': '按激活状态',
                'weight-based': '按权重'
            };
            return mapping[mode] || mode;
        };

        const normalizeLoadbalanceConfig = (payload = {}) => {
            const normalized = {
                mode: payload.mode === 'weight-based' ? 'weight-based' : 'active-first',
                options: {
                    autoResetOnAllFailed: !!(payload.options?.autoResetOnAllFailed ?? true),
                    notifyEnabled: !!(payload.options?.notifyEnabled ?? true),
                    resetCooldownSeconds: Number(payload.options?.resetCooldownSeconds ?? 30) || 30,
                    failureThreshold: Number(payload.options?.failureThreshold ?? 3) || 3,
                },
                services: {
                    claude: {
                        failureThreshold: 3,
                        currentFailures: {},
                        excludedConfigs: []
                    },
                    codex: {
                        failureThreshold: 3,
                        currentFailures: {},
                        excludedConfigs: []
                    }
                }
            };

            ['claude', 'codex'].forEach(service => {
                const section = payload.services?.[service] || {};
                const threshold = Number(section.failureThreshold ?? section.failover_count ?? 3);
                normalized.services[service].failureThreshold = Number.isFinite(threshold) && threshold > 0 ? threshold : 3;

                const rawFailures = section.currentFailures || section.current_failures || {};
                const normalizedFailures = {};
                Object.entries(rawFailures || {}).forEach(([name, count]) => {
                    const numeric = Number(count);
                    normalizedFailures[name] = Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
                });
                normalized.services[service].currentFailures = normalizedFailures;

                const excludedList = section.excludedConfigs || section.excluded_configs || [];
                normalized.services[service].excludedConfigs = Array.isArray(excludedList) ? [...excludedList] : [];
            });

            return normalized;
        };

        const applyLoadbalanceConfig = (normalized) => {
            loadbalanceConfig.mode = normalized.mode;
            loadbalanceOptions.autoResetOnAllFailed = !!normalized.options?.autoResetOnAllFailed;
            loadbalanceOptions.notifyEnabled = !!normalized.options?.notifyEnabled;
            loadbalanceOptions.resetCooldownSeconds = Number(normalized.options?.resetCooldownSeconds || 30);
            loadbalanceOptions.failureThreshold = Number(normalized.options?.failureThreshold || normalized.services?.claude?.failureThreshold || 3);
            ['claude', 'codex'].forEach(service => {
                const svc = normalized.services[service];
                loadbalanceConfig.services[service].failureThreshold = svc.failureThreshold;
                loadbalanceConfig.services[service].currentFailures = Object.assign({}, svc.currentFailures);
                loadbalanceConfig.services[service].excludedConfigs = [...svc.excludedConfigs];
            });
        };

        const buildLoadbalancePayload = () => {
            const buildServiceSection = (service) => {
                const section = loadbalanceConfig.services[service] || {};
                const threshold = Number(section.failureThreshold ?? 3);
                const normalizedThreshold = Number.isFinite(threshold) && threshold > 0 ? threshold : 3;
                const failuresPayload = {};
                Object.entries(section.currentFailures || {}).forEach(([name, count]) => {
                    const numeric = Number(count);
                    failuresPayload[name] = Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
                });
                const excludedPayload = Array.isArray(section.excludedConfigs) ? [...section.excludedConfigs] : [];
                return {
                    failureThreshold: normalizedThreshold,
                    currentFailures: failuresPayload,
                    excludedConfigs: excludedPayload
                };
            };

            return {
                mode: loadbalanceConfig.mode,
                options: {
                    autoResetOnAllFailed: !!loadbalanceOptions.autoResetOnAllFailed,
                    notifyEnabled: !!loadbalanceOptions.notifyEnabled,
                    resetCooldownSeconds: Number(loadbalanceOptions.resetCooldownSeconds || 30),
                    failureThreshold: Number(loadbalanceOptions.failureThreshold || 3),
                },
                services: {
                    claude: buildServiceSection('claude'),
                    codex: buildServiceSection('codex')
                }
            };
        };

        const updateGlobalFailureThreshold = (value) => {
            const numeric = Number(value);
            if (!Number.isFinite(numeric)) {
                return;
            }
            const threshold = Math.min(Math.max(Math.trunc(numeric), 1), 10);
            loadbalanceOptions.failureThreshold = threshold;
            ['claude', 'codex'].forEach(service => {
                loadbalanceConfig.services[service].failureThreshold = threshold;
            });
            saveLoadbalanceConfig(false);
        };

        const loadLoadbalanceConfig = async () => {
            loadbalanceLoading.value = true;
            try {
                const data = await fetchWithErrorHandling('/api/loadbalance/config');
                if (data.config) {
                    const normalized = normalizeLoadbalanceConfig(data.config);
                    applyLoadbalanceConfig(normalized);
                }
            } catch (error) {
                console.error('加载负载均衡配置失败:', error);
                ElMessage.error('加载负载均衡配置失败: ' + error.message);
                applyLoadbalanceConfig(normalizeLoadbalanceConfig({}));
            } finally {
                loadbalanceLoading.value = false;
            }
        };

        const saveLoadbalanceConfig = async (showSuccess = true) => {
            loadbalanceSaving.value = true;
            try {
                const payload = buildLoadbalancePayload();
                const result = await fetchWithErrorHandling('/api/loadbalance/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload)
                });

                if (result.success) {
                    if (showSuccess) {
                        ElMessage.success('负载均衡配置保存成功');
                    }
                    await loadLoadbalanceConfig();
                } else {
                    ElMessage.error('负载均衡配置保存失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                ElMessage.error('负载均衡配置保存失败: ' + error.message);
            } finally {
                loadbalanceSaving.value = false;
            }
        };

        const selectLoadbalanceMode = async (mode) => {
            if (loadbalanceConfig.mode === mode) {
                return;
            }
            loadbalanceConfig.mode = mode;
            await saveLoadbalanceConfig(false);
            ElMessage.success(`已切换到${getLoadbalanceModeText(mode)}模式`);
        };

        const weightedTargets = computed(() => {
            const result = { claude: [], codex: [] };
            ['claude', 'codex'].forEach(service => {
                const metadata = configMetadata[service] || {};
                const threshold = loadbalanceConfig.services[service]?.failureThreshold || 3;
                const failures = loadbalanceConfig.services[service]?.currentFailures || {};
                const excluded = loadbalanceConfig.services[service]?.excludedConfigs || [];
                const list = Object.entries(metadata)
                    .filter(([, meta]) => !meta?.deleted)
                    .map(([name, meta]) => {
                        const weight = Number(meta?.weight ?? 0);
                        return {
                            name,
                            weight: Number.isFinite(weight) ? weight : 0,
                            failures: failures[name] || 0,
                        threshold,
                        excluded: excluded.includes(name),
                        isActive: services[service].config === name
                    };
                });
                list.sort((a, b) => {
                    if (b.weight !== a.weight) {
                        return b.weight - a.weight;
                    }
                    return a.name.localeCompare(b.name);
                });
                result[service] = list;
            });
            return result;
        });

        const resetLoadbalanceFailures = async (service) => {
            if (resettingFailures[service]) {
                return;
            }
            resettingFailures[service] = true;
            try {
                const result = await fetchWithErrorHandling('/api/loadbalance/reset-failures', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ service })
                });

                if (result.success) {
                    ElMessage.success(result.message || '失败计数已重置');
                    await loadLoadbalanceConfig();
                } else {
                    ElMessage.error('重置失败计数失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                ElMessage.error('重置失败计数失败: ' + error.message);
            } finally {
                resettingFailures[service] = false;
            }
        };

        // API 请求方法
        // Token 管理
        const getAuthToken = () => {
            return localStorage.getItem('clp_auth_token') || '';
        };

        const setAuthToken = (token) => {
            if (token) {
                localStorage.setItem('clp_auth_token', token);
            } else {
                localStorage.removeItem('clp_auth_token');
            }
        };

        const promptForToken = async () => {
            return new Promise((resolve) => {
                ElMessageBox.prompt('请输入访问令牌 (Token)', '身份验证', {
                    confirmButtonText: '确定',
                    cancelButtonText: '取消',
                    inputPlaceholder: '请输入 clp_ 开头的 token',
                    inputPattern: /^clp_.+/,
                    inputErrorMessage: 'Token 格式不正确，应以 clp_ 开头',
                    closeOnClickModal: false,
                    closeOnPressEscape: false,
                    showClose: false
                }).then(({ value }) => {
                    setAuthToken(value);
                    resolve(value);
                }).catch(() => {
                    ElMessage.warning('未输入令牌，将无法访问服务');
                    resolve(null);
                });
            });
        };

        const fetchWithErrorHandling = async (url, options = {}) => {
            try {
                // 自动添加 token header
                const token = getAuthToken();
                if (token) {
                    options.headers = options.headers || {};
                    options.headers['X-API-Key'] = token;
                }

                const response = await fetch(url, options);

                // 处理 401 未授权错误
                if (response.status === 401) {
                    ElMessage.warning('身份验证失败，请输入有效的访问令牌');
                    const newToken = await promptForToken();
                    if (newToken) {
                        // 重试请求
                        options.headers = options.headers || {};
                        options.headers['X-API-Key'] = newToken;
                        const retryResponse = await fetch(url, options);
                        if (!retryResponse.ok) {
                            throw new Error(`HTTP ${retryResponse.status}: ${retryResponse.statusText}`);
                        }
                        return await retryResponse.json();
                    } else {
                        throw new Error('未授权访问');
                    }
                }

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return await response.json();
            } catch (error) {
                console.error(`API请求失败 ${url}:`, error);
                throw error;
            }
        };
        
        // 加载状态数据
        const loadStatus = async () => {
            try {
                const data = await fetchWithErrorHandling('/api/status');
                updateServiceStatus(data);
                updateStats(data);
            } catch (error) {
                ElMessage.error('获取状态失败: ' + error.message);
            }
        };
        
        // 更新服务状态
        const updateServiceStatus = (data) => {
            if (data.services?.claude) {
                Object.assign(services.claude, data.services.claude);
            }
            if (data.services?.codex) {
                Object.assign(services.codex, data.services.codex);
            }
        };
        
        // 更新统计信息
        const updateStats = (data) => {
            stats.requestCount = data.request_count || 0;
            stats.configCount = data.config_count || 0;
            stats.filterCount = data.filter_count || 0;
            stats.headerFilterCount = data.header_filter_count || 0;
            stats.endpointFilterCount = data.endpoint_filter_count || 0;

            const summary = data.usage_summary || null;
            if (summary) {
                const perService = {};
                const totalMetrics = createEmptyMetrics();
                Object.entries(summary.per_service || {}).forEach(([service, payload]) => {
                    if (!service || service === 'unknown') {
                        return;
                    }
                    const adjusted = adjustUsageBlockForService(service, payload || {});
                    perService[service] = adjusted;
                    mergeMetricsInto(totalMetrics, adjusted.displayMetrics || adjusted.metrics);
                });

                ['claude', 'codex'].forEach(service => {
                    if (!perService[service]) {
                        perService[service] = adjustUsageBlockForService(service, {});
                    }
                });

                usageSummary.perService = perService;

                let totalsBlock;
                if (Object.keys(perService).length === 0 && summary.totals) {
                    totalsBlock = adjustUsageBlockForService('codex', summary.totals || {});
                } else {
                    totalsBlock = updateFormattedFromMetrics({
                        metrics: Object.assign(createEmptyMetrics(), totalMetrics),
                        displayMetrics: Object.assign(createEmptyMetrics(), totalMetrics),
                        formatted: createEmptyFormatted()
                    });
                }
                usageSummary.totals = Object.assign(createEmptyMetrics(), totalsBlock.displayMetrics || totalsBlock.metrics);
                usageSummary.formattedTotals = Object.assign(createEmptyFormatted(), totalsBlock.displayFormatted || totalsBlock.formatted);
            } else {
                resetUsageSummary();
            }
        };
        
        // 加载日志
        const loadLogs = async () => {
            logsLoading.value = true;
            try {
                const data = await fetchWithErrorHandling('/api/logs');
                logs.value = Array.isArray(data) ? data : [];
            } catch (error) {
                ElMessage.error('获取日志失败: ' + error.message);
                logs.value = [];
            } finally {
                logsLoading.value = false;
            }
        };
        
        // 加载配置选项
        const loadConfigOptions = async () => {
            try {
                // 加载Claude配置选项
                const claudeData = await fetchWithErrorHandling('/api/config/claude');
                if (claudeData.content) {
                    const configs = JSON.parse(claudeData.content);
                    const entries = Object.entries(configs).filter(([key, value]) => key && key !== 'undefined' && value !== undefined);
                    const metadata = {};
                    const available = [];
                    entries.forEach(([key, value]) => {
                        const weightValue = Number(value?.weight ?? 0);
                        const deleted = !!value?.deleted;
                        const deletedAt = typeof value?.deleted_at === 'string' ? value.deleted_at : null;
                        metadata[key] = {
                            weight: Number.isFinite(weightValue) ? weightValue : 0,
                            active: !deleted && !!value?.active,
                            deleted,
                            deletedAt
                        };
                        if (!deleted) {
                            available.push(key);
                        }
                    });
                    claudeConfigs.value = available;
                    configMetadata.claude = metadata;
                } else {
                    claudeConfigs.value = [];
                    configMetadata.claude = {};
                }
                
                // 加载Codex配置选项
                const codexData = await fetchWithErrorHandling('/api/config/codex');
                if (codexData.content) {
                    const configs = JSON.parse(codexData.content);
                    const entries = Object.entries(configs).filter(([key, value]) => key && key !== 'undefined' && value !== undefined);
                    const metadata = {};
                    const available = [];
                    entries.forEach(([key, value]) => {
                        const weightValue = Number(value?.weight ?? 0);
                        const deleted = !!value?.deleted;
                        const deletedAt = typeof value?.deleted_at === 'string' ? value.deleted_at : null;
                        metadata[key] = {
                            weight: Number.isFinite(weightValue) ? weightValue : 0,
                            active: !deleted && !!value?.active,
                            deleted,
                            deletedAt
                        };
                        if (!deleted) {
                            available.push(key);
                        }
                    });
                    codexConfigs.value = available;
                    configMetadata.codex = metadata;
                } else {
                    codexConfigs.value = [];
                    configMetadata.codex = {};
                }
            } catch (error) {
                console.error('加载配置选项失败:', error);
            }
        };
        
        // 主数据加载方法
        const loadData = async () => {
            loading.value = true;
            try {
                await loadConfigOptions();
                await Promise.all([
                    loadStatus(),
                    loadLogs(),
                    loadRoutingConfig(),
                    loadLoadbalanceConfig()
                ]);
                updateLastUpdateTime();
            } catch (error) {
                console.error('加载数据失败:', error);
                ElMessage.error('数据加载失败');
            } finally {
                loading.value = false;
            }
        };
        
        // 格式化倒计时显示（分:秒）
        const formatCountdown = (seconds) => {
            const mins = Math.floor(seconds / 60);
            const secs = seconds % 60;
            return `${mins}:${secs.toString().padStart(2, '0')}`;
        };

        // 启动自动刷新定时器
        const startAutoRefresh = () => {
            stopAutoRefresh();  // 先清除可能存在的旧定时器
            autoRefreshCountdown.value = AUTO_REFRESH_INTERVAL;
            
            autoRefreshTimer.value = setInterval(() => {
                autoRefreshCountdown.value--;
                
                if (autoRefreshCountdown.value <= 0) {
                    performAutoRefresh();  // 触发自动刷新
                }
            }, 1000);  // 每秒更新一次
        };

        // 停止自动刷新定时器
        const stopAutoRefresh = () => {
            if (autoRefreshTimer.value) {
                clearInterval(autoRefreshTimer.value);
                autoRefreshTimer.value = null;
            }
        };

        // 执行自动刷新（局部数据刷新）
        const performAutoRefresh = async () => {
            try {
                await loadData();  // 刷新数据，不重载页面
                startAutoRefresh();  // 重启定时器
            } catch (error) {
                console.error('自动刷新失败:', error);
                // 刷新失败也要重启定时器，避免停止工作
                startAutoRefresh();
            }
        };
        
        // 刷新页面（局部数据刷新）
        const refreshData = async () => {
            stopAutoRefresh();  // 停止自动刷新
            loading.value = true;
            try {
                await loadData();  // 局部数据刷新
                ElMessage.success('数据已刷新');
            } catch (error) {
                ElMessage.error('刷新失败: ' + error.message);
            } finally {
                loading.value = false;
                startAutoRefresh();  // 重启自动刷新
            }
        };
        
        // 更新最后更新时间
        const updateLastUpdateTime = () => {
            const now = new Date();
            const timeString = now.toLocaleTimeString('zh-CN', { hour12: false });
            lastUpdate.value = `上次刷新时刻: ${timeString}`;
        };
        
        // 配置切换
        const switchConfig = async (serviceName, configName) => {
            if (!configName) return;
            if (isLoadbalanceWeightMode.value) {
                ElMessage.info('负载均衡权重模式生效，无法手动切换转发目标');
                return;
            }
            
            try {
                const result = await fetchWithErrorHandling('/api/switch-config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        service: serviceName,
                        config: configName
                    })
                });
                
                if (result.success) {
                    ElMessage.success(`${serviceName}配置已切换到: ${configName}`);
                    // 更新本地状态，避免不必要的重新加载
                    services[serviceName].config = configName;
                    updateLastUpdateTime();
                } else {
                    ElMessage.error(result.message || '配置切换失败');
                    // 失败时恢复原始配置选择
                    await loadStatus();
                }
            } catch (error) {
                ElMessage.error('配置切换失败: ' + error.message);
                // 错误时恢复原始配置选择
                await loadStatus();
            }
        };
        
        // 配置抽屉相关
        const openConfigDrawer = async () => {
            configDrawerVisible.value = true;
            await loadConfigs();
        };
        
        const closeConfigDrawer = () => {
            configDrawerVisible.value = false;
        };
        
        const loadConfigs = async () => {
            try {
                // 加载Claude配置
                const claudeData = await fetchWithErrorHandling('/api/config/claude');
                const claudeContent = claudeData?.content ?? '{}';
                configContents.claude = claudeContent.trim() ? claudeContent : '{}';
                syncJsonToForm('claude');

                // 加载Codex配置
                const codexData = await fetchWithErrorHandling('/api/config/codex');
                const codexContent = codexData?.content ?? '{}';
                configContents.codex = codexContent.trim() ? codexContent : '{}';
                syncJsonToForm('codex');
            } catch (error) {
                const errorMsg = '// 加载失败: ' + error.message;
                configContents.claude = errorMsg;
                configContents.codex = errorMsg;
                // 错误情况下清空友好表单
                friendlyConfigs.claude = [];
                friendlyConfigs.codex = [];
            }
        };
        
        // 友好表单配置管理方法
        const startAddingSite = (service) => {
            editingNewSite[service] = true;
            newSiteData[service] = {
                name: '',
                baseUrl: 'https://',
                authType: 'auth_token',
                authValue: '',
                active: false,
                weight: 0,
                deleted: false,
                deletedAt: null
            };
            // 自动聚焦到站点名称输入框
            nextTick(() => {
                const input = document.querySelector('.new-site-name-input input');
                if (input) {
                    input.focus();
                }
            });
        };

        const confirmAddSite = async (service) => {
            if (newSiteData[service].name.trim()) {
                // 如果新站点设置为激活，先关闭其他站点
                if (newSiteData[service].active) {
                    friendlyConfigs[service].forEach(site => {
                        site.active = false;
                    });
                    newSiteData[service].deleted = false;
                    newSiteData[service].deletedAt = null;
                }
                if (newSiteData[service].deleted) {
                    newSiteData[service].active = false;
                    if (!newSiteData[service].deletedAt) {
                        newSiteData[service].deletedAt = new Date().toISOString();
                    }
                } else {
                    newSiteData[service].deletedAt = null;
                }
                // 插入到第一个位置
                friendlyConfigs[service].unshift({...newSiteData[service]});
                editingNewSite[service] = false;
                syncFormToJson(service);

                // 自动保存配置
                await saveConfigForService(service);
            }
        };

        const cancelAddSite = (service) => {
            editingNewSite[service] = false;
            newSiteData[service] = {
                name: '',
                baseUrl: 'https://',
                authType: 'auth_token',
                authValue: '',
                active: false,
                weight: 0,
                deleted: false,
                deletedAt: null
            };
        };

        const saveInteractiveConfig = async (service) => {
            await saveConfigForService(service);
        };

        const removeConfigSite = async (service, index) => {
            const siteName = friendlyConfigs[service][index]?.name || '未命名站点';
            try {
                await ElMessageBox.confirm(
                    `确定要删除站点 "${siteName}" 吗？此操作不可撤销。`,
                    '确认删除站点',
                    {
                        confirmButtonText: '确定',
                        cancelButtonText: '取消',
                        type: 'warning',
                    }
                );
                
                friendlyConfigs[service].splice(index, 1);
                syncFormToJson(service);
                
                // 自动保存配置
                await saveConfigForService(service);
                
                ElMessage.success('站点删除成功');
            } catch (error) {
                if (error !== 'cancel') {
                    ElMessage.error('删除站点失败: ' + error.message);
                }
            }
        };

        // 处理激活状态变化（单选逻辑）
        const handleActiveChange = (service, activeIndex, newValue) => {
            const targetSite = friendlyConfigs[service][activeIndex];
            if (newValue && targetSite) {
                targetSite.deleted = false;
                targetSite.deletedAt = null;
                friendlyConfigs[service].forEach((site, index) => {
                    if (index !== activeIndex) {
                        site.active = false;
                    } else {
                        site.active = true;
                    }
                });
            }
            syncFormToJson(service);
        };

        const handleDeletedChange = (service, index, newValue) => {
            const site = friendlyConfigs[service][index];
            if (!site) return;
            site.deleted = !!newValue;
            if (site.deleted) {
                site.active = false;
                site.deletedAt = new Date().toISOString();
            } else {
                site.deletedAt = null;
            }
            syncFormToJson(service);
        };

        const handleNewSiteDeletedChange = (service, newValue) => {
            const siteDraft = newSiteData[service];
            if (!siteDraft) return;
            siteDraft.deleted = !!newValue;
            if (siteDraft.deleted) {
                siteDraft.active = false;
                siteDraft.deletedAt = new Date().toISOString();
            } else {
                siteDraft.deletedAt = null;
            }
        };

        // 从表单同步到JSON
        const syncFormToJson = (service) => {
            if (syncInProgress.value) return;

            try {
                syncInProgress.value = true;
                const jsonObj = {};
                friendlyConfigs[service].forEach(site => {
                    if (site.name && site.name.trim()) {
                        const config = {
                            base_url: site.baseUrl || '',
                            active: site.active || false
                        };

                        // 根据认证类型设置相应字段
                        if (site.authType === 'auth_token') {
                            config.auth_token = site.authValue || '';
                            config.api_key = '';
                        } else {
                            config.api_key = site.authValue || '';
                            config.auth_token = '';
                        }

                        const weightValue = Number(site.weight ?? 0);
                        config.weight = Number.isFinite(weightValue) ? weightValue : 0;

                        const isDeleted = !!site.deleted;
                        config.deleted = isDeleted;
                        if (isDeleted) {
                            const timestamp = (typeof site.deletedAt === 'string' && site.deletedAt)
                                ? site.deletedAt
                                : new Date().toISOString();
                            config.deleted_at = timestamp;
                            site.deletedAt = timestamp;
                            config.active = false;
                        } else {
                            site.deletedAt = null;
                        }

                        jsonObj[site.name.trim()] = config;
                    }
                });

                configContents[service] = JSON.stringify(jsonObj, null, 2);
            } catch (error) {
                console.error('同步表单到JSON失败:', error);
            } finally {
                // 延迟重置状态，确保watch不会立即触发
                nextTick(() => {
                    syncInProgress.value = false;
                });
            }
        };

        // 从JSON同步到表单
        const syncJsonToForm = (service) => {
            if (syncInProgress.value) return;

            try {
                syncInProgress.value = true;
                const content = configContents[service];
                if (!content || content.trim() === '' || content.trim() === '{}') {
                    friendlyConfigs[service] = [];
                    return;
                }

                const jsonObj = JSON.parse(content);
                const sites = [];

                Object.entries(jsonObj).forEach(([siteName, config]) => {
                    if (config && typeof config === 'object') {
                        // 判断使用哪种认证方式
                        let authType = 'auth_token';
                        let authValue = '';

                        if (config.api_key && config.api_key.trim()) {
                            authType = 'api_key';
                            authValue = config.api_key;
                        } else if (config.auth_token) {
                            authType = 'auth_token';
                            authValue = config.auth_token;
                        }

                        let weightValue = Number(config.weight ?? 0);
                        if (!Number.isFinite(weightValue)) {
                            weightValue = 0;
                        }

                        const deleted = !!config.deleted;
                        const deletedAt = typeof config.deleted_at === 'string' ? config.deleted_at : null;
                        const activeValue = deleted ? false : !!config.active;

                        sites.push({
                            name: siteName,
                            baseUrl: config.base_url || '',
                            authType: authType,
                            authValue: authValue,
                            active: activeValue,
                            weight: weightValue,
                            deleted,
                            deletedAt
                        });
                    }
                });

                friendlyConfigs[service] = sites;
            } catch (error) {
                console.error('同步JSON到表单失败:', error);
                // JSON解析失败时保持现有表单数据不变
            } finally {
                // 延迟重置状态
                nextTick(() => {
                    syncInProgress.value = false;
                });
            }
        };

        const saveConfigForService = async (service) => {
            const content = configContents[service];

            if (!content.trim()) {
                ElMessage.warning('配置内容不能为空');
                return;
            }

            // 验证JSON格式
            try {
                JSON.parse(content);
            } catch (e) {
                ElMessage.error('JSON格式错误: ' + e.message);
                return;
            }

            configSaving.value = true;
            try {
                const result = await fetchWithErrorHandling(`/api/config/${service}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ content })
                });

                if (result.success) {
                    ElMessage.success(result.message || '配置保存成功');
                    await loadData();
                } else {
                    ElMessage.error('保存失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                ElMessage.error('保存失败: ' + error.message);
            } finally {
                configSaving.value = false;
            }
        };

        const saveConfig = async () => {
            const service = activeConfigTab.value;
            await saveConfigForService(service);
        };
        
        // Body Filter 抽屉相关
        const openBodyFilterDrawer = async () => {
            bodyFilterDrawerVisible.value = true;
            await loadFilter();
        };
        
        // 添加过滤规则
        const addFilterRule = () => {
            filterRules.value.push({
                source: '',
                target: '',
                op: 'replace'
            });
        };
        
        // 删除过滤规则
        const removeFilterRule = (index) => {
            filterRules.value.splice(index, 1);
        };
        
        const closeBodyFilterDrawer = () => {
            bodyFilterDrawerVisible.value = false;
        };

        // Header Filter 相关方法（新增）
        const openHeaderFilterDrawer = async () => {
            headerFilterDrawerVisible.value = true;
            await loadHeaderFilter();
        };

        const closeHeaderFilterDrawer = () => {
            headerFilterDrawerVisible.value = false;
        };

        const loadHeaderFilter = async () => {
            try {
                const data = await fetchWithErrorHandling('/api/header-filter');
                headerFilterConfig.enabled = data.config.enabled ?? true;
                headerFilterConfig.blocked_headers = data.config.blocked_headers || [];
            } catch (error) {
                headerFilterConfig.enabled = true;
                headerFilterConfig.blocked_headers = [];
                ElMessage.error('加载 Header 过滤配置失败: ' + error.message);
            }
        };

        const saveHeaderFilter = async () => {
            headerFilterSaving.value = true;
            try {
                const validHeaders = headerFilterConfig.blocked_headers.filter(h => h && h.trim());

                const payload = {
                    enabled: headerFilterConfig.enabled,
                    blocked_headers: validHeaders
                };

                const response = await fetch('/api/header-filter', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const result = await response.json();

                if (result.success) {
                    ElMessage.success(result.message);
                    await refreshData();
                } else {
                    ElMessage.error(result.error || '保存失败');
                }
            } catch (error) {
                ElMessage.error('保存 Header 过滤配置失败: ' + error.message);
            } finally {
                headerFilterSaving.value = false;
            }
        };

        const addBlockedHeader = () => {
            headerFilterConfig.blocked_headers.push('');
        };

        const removeBlockedHeader = (index) => {
            headerFilterConfig.blocked_headers.splice(index, 1);
        };

        const applyHeaderPreset = (preset) => {
            if (preset === 'privacy') {
                headerFilterConfig.enabled = true;
                headerFilterConfig.blocked_headers = [
                    'x-forwarded-for',
                    'x-forwarded-proto',
                    'x-forwarded-scheme',
                    'x-real-ip',
                    'x-forwarded-host',
                    'x-forwarded-port',
                    'x-forwarded-server',
                    'cf-connecting-ip',
                    'cf-ipcountry',
                    'true-client-ip'
                ];
                ElMessage.success('已应用隐私保护模式');
            } else if (preset === 'debug') {
                headerFilterConfig.enabled = false;
                headerFilterConfig.blocked_headers = [];
                ElMessage.success('已应用调试模式（全透传）');
            } else if (preset === 'default') {
                headerFilterConfig.enabled = true;
                headerFilterConfig.blocked_headers = [
                    'x-forwarded-for',
                    'x-forwarded-proto',
                    'x-forwarded-scheme',
                    'x-real-ip'
                ];
                ElMessage.success('已应用默认配置');
            }
        };

        // Endpoint Filter 相关方法（新增）
        const openEndpointFilterDrawer = async () => {
            endpointFilterDrawerVisible.value = true;
            await loadEndpointFilter();
        };
        const closeEndpointFilterDrawer = () => {
            endpointFilterDrawerVisible.value = false;
        };
        const HTTP_METHOD_OPTIONS = ['*','GET','POST','PUT','DELETE','PATCH','OPTIONS'];

        const normalizeRuleForForm = (rule) => {
            const r = { id: '', services: ['claude','codex'], methods: ['*'], matchType: 'path', matchValue: '', queryPairs: [], action: { status: 403, message: 'Endpoint is blocked by proxy' } };
            if (typeof rule.id === 'string' && rule.id.trim()) r.id = rule.id.trim();
            if (Array.isArray(rule.services) && rule.services.length) r.services = rule.services.map(s=>String(s).toLowerCase());
            if (Array.isArray(rule.methods) && rule.methods.length) r.methods = rule.methods.map(m=>String(m).toUpperCase());
            if (typeof rule.path === 'string' && rule.path.trim()) { r.matchType = 'path'; r.matchValue = rule.path; }
            else if (typeof rule.prefix === 'string' && rule.prefix.trim()) { r.matchType = 'prefix'; r.matchValue = rule.prefix; }
            else if (typeof rule.regex === 'string' && rule.regex.trim()) { r.matchType = 'regex'; r.matchValue = rule.regex; }
            const q = rule.query || {};
            if (q && typeof q === 'object') {
                r.queryPairs = Object.entries(q).map(([k,v])=>({ key: String(k), value: (v===null||v===undefined)?'':String(v) }));
            }
            const a = rule.action || {};
            r.action = { status: Number(a.status ?? 403), message: String(a.message ?? 'Endpoint is blocked by proxy') };
            return r;
        };
        const denormalizeRuleForSave = (r) => {
            const rule = {};
            if (r.id && r.id.trim()) rule.id = r.id.trim();
            if (Array.isArray(r.services) && r.services.length && !(r.services.length===2 && r.services.includes('claude') && r.services.includes('codex'))) {
                rule.services = r.services.map(s=>String(s).toLowerCase());
            }
            if (Array.isArray(r.methods) && r.methods.length && !(r.methods.length===1 && r.methods[0]==='*')) {
                rule.methods = r.methods.map(m=>String(m).toUpperCase());
            }
            if (r.matchType === 'path') rule.path = r.matchValue || '';
            else if (r.matchType === 'prefix') rule.prefix = r.matchValue || '';
            else if (r.matchType === 'regex') rule.regex = r.matchValue || '';
            const qp = Array.isArray(r.queryPairs) ? r.queryPairs : [];
            if (qp.length) {
                const q = {};
                qp.forEach(({key,value})=>{ if (String(key).trim()) q[String(key)] = (String(value).trim()||String(value)==='') ? String(value) : String(value); });
                rule.query = q;
            }
            rule.action = { type: 'block', status: Number(r.action?.status ?? 403), message: String(r.action?.message ?? 'Endpoint is blocked by proxy') };
            return rule;
        };
        const loadEndpointFilter = async () => {
            try {
                const data = await fetchWithErrorHandling('/api/endpoint-filter');
                const cfg = data.config || { enabled: true, rules: [] };
                endpointFilterConfig.enabled = !!cfg.enabled;
                const rules = Array.isArray(cfg.rules) ? cfg.rules : [];
                endpointFilterConfig.rules = rules.map(normalizeRuleForForm);
            } catch (e) {
                endpointFilterConfig.enabled = true;
                endpointFilterConfig.rules = [];
                ElMessage.error('加载 Endpoint 过滤配置失败: ' + e.message);
            }
        };
        const saveEndpointFilter = async () => {
            try {
                const payload = {
                    enabled: endpointFilterConfig.enabled,
                    rules: endpointFilterConfig.rules.map(denormalizeRuleForSave)
                };
                const result = await fetchWithErrorHandling('/api/endpoint-filter', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (result.success) {
                    ElMessage.success(result.message || 'Endpoint 过滤配置保存成功');
                    await refreshData();
                } else {
                    ElMessage.error(result.error || '保存失败');
                }
            } catch (e) {
                ElMessage.error('保存 Endpoint 过滤配置失败: ' + e.message);
            }
        };
        const addEndpointRule = () => {
            endpointFilterConfig.rules.push({
                id: '', services: ['claude','codex'], methods: ['*'], matchType: 'path', matchValue: '', queryPairs: [], action: { status: 403, message: 'Endpoint is blocked by proxy' }
            });
        };
        const removeEndpointRule = (idx) => {
            endpointFilterConfig.rules.splice(idx, 1);
        };
        const addQueryPair = (rule) => {
            rule.queryPairs.push({ key: '', value: '' });
        };
        const removeQueryPair = (rule, i) => {
            rule.queryPairs.splice(i, 1);
        };

        const loadFilter = async () => {
            try {
                const data = await fetchWithErrorHandling('/api/filter');
                filterContent.value = data.content || '[]';
                
                // 解析JSON并转换为规则数组
                try {
                    let parsedRules = JSON.parse(filterContent.value);
                    if (!Array.isArray(parsedRules)) {
                        parsedRules = [parsedRules];
                    }
                    filterRules.value = parsedRules.map(rule => ({
                        source: rule.source || '',
                        target: rule.target || '',
                        op: rule.op || 'replace'
                    }));
                } catch (e) {
                    // 如果JSON解析失败，初始化为空数组
                    filterRules.value = [];
                }
            } catch (error) {
                filterRules.value = [];
                ElMessage.error('加载过滤规则失败: ' + error.message);
            }
        };
        
        const saveFilter = async () => {
            // 过滤掉空规则
            const validRules = filterRules.value.filter(rule => rule.source && rule.source.trim());
            
            if (validRules.length === 0) {
                const emptyRules = '[]';
                filterContent.value = emptyRules;
            } else {
                // 验证规则
                for (const rule of validRules) {
                    if (!['replace', 'remove'].includes(rule.op)) {
                        ElMessage.error('op 字段必须是 replace 或 remove');
                        return;
                    }
                    if (rule.op === 'replace' && !rule.target) {
                        ElMessage.error('replace 操作必须填写替换后的文本');
                        return;
                    }
                }
                
                // 转换为JSON格式
                const jsonRules = validRules.map(rule => {
                    const obj = {
                        source: rule.source,
                        op: rule.op
                    };
                    if (rule.op === 'replace') {
                        obj.target = rule.target || '';
                    }
                    return obj;
                });
                
                filterContent.value = JSON.stringify(jsonRules, null, 2);
            }
            
            filterSaving.value = true;
            try {
                const result = await fetchWithErrorHandling('/api/filter', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ content: filterContent.value })
                });
                
                if (result.success) {
                    ElMessage.success(result.message || '过滤规则保存成功');
                    await loadData();
                } else {
                    ElMessage.error('保存失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                ElMessage.error('保存失败: ' + error.message);
            } finally {
                filterSaving.value = false;
            }
        };
        
        // 工具方法
        const formatTimestamp = (timestamp) => {
            if (!timestamp) return '-';

            try {
                const date = new Date(timestamp);
                const year = date.getFullYear();
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const day = String(date.getDate()).padStart(2, '0');
                const hours = String(date.getHours()).padStart(2, '0');
                const minutes = String(date.getMinutes()).padStart(2, '0');
                const seconds = String(date.getSeconds()).padStart(2, '0');

                return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
            } catch (e) {
                return timestamp;
            }
        };
        
        const truncatePath = (path) => {
            // 不截断URL，显示完整内容
            return path || '-';
        };
        
        const getStatusTagType = (statusCode) => {
            if (!statusCode) return '';
            
            const status = parseInt(statusCode);
            if (status >= 200 && status < 300) return 'success';
            if (status >= 400 && status < 500) return 'warning';
            if (status >= 500) return 'danger';
            return '';
        };

        const getFilteredHeaders = (log) => {
            const original = log.original_headers || {};
            const target = log.target_headers || {};

            const filtered = [];
            for (const key in original) {
                if (!(key in target)) {
                    filtered.push(`${key}: ${original[key]}`);
                }
            }
            return filtered;
        };

        // 日志详情相关方法
        const decodeBodyContent = (encodedContent) => {
            if (!encodedContent) {
                return '';
            }

            try {
                const decodedBytes = atob(encodedContent);
                const decodedText = decodeURIComponent(decodedBytes.split('').map(c =>
                    '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
                ).join(''));

                try {
                    const jsonObj = JSON.parse(decodedText);
                    return JSON.stringify(jsonObj, null, 2);
                } catch {
                    return decodedText;
                }
            } catch (error) {
                console.error('解码请求体失败:', error);
                return '解码失败: ' + error.message;
            }
        };

        const decodeContentAsync = (encodedContent, targetRef) => {
            targetRef.value = '';
            if (!encodedContent) {
                return;
            }
            setTimeout(() => {
                targetRef.value = decodeBodyContent(encodedContent);
            }, 0);
        };

        const showLogDetail = (log) => {
            if (!log || !log.id) {
                ElMessage.error('无法加载日志详情：缺少日志ID');
                return;
            }

            // 打开抽屉并清空旧内容
            logDetailVisible.value = true;
            activeLogTab.value = 'basic';
            logDetailError.value = null;
            logDetailLoading.value = true;
            logDetailRequestId.value = log.id;
            selectedLog.value = { ...log };
            decodedRequestBody.value = '';
            decodedOriginalRequestBody.value = '';
            decodedResponseContent.value = '';

            fetchWithErrorHandling(`/api/logs/${encodeURIComponent(log.id)}`)
                .then((detail) => {
                    if (logDetailRequestId.value !== log.id) {
                        return;
                    }
                    selectedLog.value = detail;
                    decodeContentAsync(detail.filtered_body, decodedRequestBody);
                    decodeContentAsync(detail.original_body, decodedOriginalRequestBody);
                    decodeContentAsync(detail.response_content, decodedResponseContent);
                })
                .catch((error) => {
                    if (logDetailRequestId.value !== log.id) {
                        return;
                    }
                    logDetailError.value = error.message;
                    ElMessage.error('获取日志详情失败: ' + error.message);
                })
                .finally(() => {
                    if (logDetailRequestId.value === log.id) {
                        logDetailLoading.value = false;
                    }
                });
        };
        
        // 加载所有日志（默认只显示最近100条）
        const ALL_LOGS_CACHE_TTL = 5000;
        let lastAllLogsFetchAt = 0;

        const loadAllLogs = async (force = false) => {
            const now = Date.now();
            if (!force && allLogs.value.length > 0 && (now - lastAllLogsFetchAt) < ALL_LOGS_CACHE_TTL) {
                return;
            }
            allLogsLoading.value = true;
            try {
                const data = await fetchWithErrorHandling('/api/logs/all');
                const logs = Array.isArray(data) ? data : [];
                allLogs.value = logs;
                lastAllLogsFetchAt = Date.now();
            } catch (error) {
                ElMessage.error('获取所有日志失败: ' + error.message);
                allLogs.value = [];
            } finally {
                allLogsLoading.value = false;
            }
        };
        
        // 查看所有日志
        const viewAllLogs = () => {
            allLogsVisible.value = true;
            loadAllLogs();
        };
        
        // 刷新所有日志
        const refreshAllLogs = () => {
            loadAllLogs(true);
        };
        
        // 格式化请求体JSON
        const formatJsonContent = (bodyRef) => {
            if (!bodyRef.value) {
                ElMessage.warning('没有请求体内容');
                return;
            }

            try {
                const jsonObj = JSON.parse(bodyRef.value);
                bodyRef.value = JSON.stringify(jsonObj, null, 2);
                ElMessage.success('JSON格式化成功');
            } catch (error) {
                ElMessage.error('不是有效的JSON格式');
            }
        };

        const formatFilteredRequestBody = () => formatJsonContent(decodedRequestBody);
        const formatOriginalRequestBody = () => formatJsonContent(decodedOriginalRequestBody);
        const formatResponseContent = () => formatJsonContent(decodedResponseContent);
        
        
        // 对Headers按字母排序
        const getSortedHeaderKeys = (headers) => {
            if (!headers || typeof headers !== 'object') {
                return [];
            }
            return Object.keys(headers).sort((a, b) => {
                // 不区分大小写的字母排序
                return a.toLowerCase().localeCompare(b.toLowerCase());
            });
        };

        // 复制到剪贴板
        const copyToClipboard = async (text) => {
            try {
                await navigator.clipboard.writeText(text);
                ElMessage.success('已复制到剪贴板');
            } catch (error) {
                // 降级方案
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.style.position = 'fixed';
                textArea.style.opacity = '0';
                document.body.appendChild(textArea);
                textArea.select();
                try {
                    document.execCommand('copy');
                    ElMessage.success('已复制到剪贴板');
                } catch (err) {
                    ElMessage.error('复制失败');
                }
                document.body.removeChild(textArea);
            }
        };
        
        // 清空所有日志
        const clearAllLogs = async () => {
            try {
                await ElMessageBox.confirm(
                    '确定要清空所有日志吗？此操作不可撤销。',
                    '确认清空',
                    {
                        confirmButtonText: '确定',
                        cancelButtonText: '取消',
                        type: 'warning',
                    }
                );
                
                const result = await fetchWithErrorHandling('/api/logs', {
                    method: 'DELETE'
                });
                
                if (result.success) {
                    ElMessage.success('日志已清空');
                    // 刷新页面数据
                    window.location.reload();
                } else {
                    ElMessage.error('清空日志失败: ' + (result.error || '未知错误'));
                }
            } catch (error) {
                if (error !== 'cancel') {
                    ElMessage.error('清空日志失败: ' + error.message);
                }
            }
        };
        
        // 添加对JSON内容变化的监听，实现JSON到表单的同步
        // 监听Claude配置JSON变化
        watch(() => configContents.claude, (newValue) => {
            // 延迟执行，避免在同步过程中产生循环调用
            nextTick(() => {
                syncJsonToForm('claude');
            });
        });

        // 监听Codex配置JSON变化
        watch(() => configContents.codex, (newValue) => {
            // 延迟执行，避免在同步过程中产生循环调用
            nextTick(() => {
                syncJsonToForm('codex');
            });
        });

        // 实时请求相关方法
        const initRealTimeConnections = () => {
            try {
                realtimeManager.value = new RealTimeManager();
                const removeListener = realtimeManager.value.addListener(handleRealTimeEvent);

                // 页面卸载时清理
                window.addEventListener('beforeunload', () => {
                    removeListener();
                    if (realtimeManager.value) {
                        realtimeManager.value.destroy();
                    }
                });

                // 禁用自动连接，改为手动连接模式
                // setTimeout(() => {
                //     realtimeManager.value.connectAll();
                //     console.log('实时连接管理器初始化成功');
                // }, 1000); // 延迟1秒再连接
                console.log('实时连接管理器初始化成功，请手动点击重连按钮连接服务器');
            } catch (error) {
                console.error('初始化实时连接失败:', error);
                ElMessage.error('实时连接初始化失败: ' + error.message);
            }
        };

        const handleRealTimeEvent = (event) => {
            try {
                switch (event.type) {
                    case 'lb_switch':
                        if (loadbalanceOptions.notifyEnabled) {
                            const msg = `服务 [${event.service}] 上游切换：${event.from_channel} → ${event.to_channel}（失败 ${event.failures}/${event.threshold}，尝试 #${event.attempt}）`;
                            ElMessage.warning({ message: msg, duration: 3000, showClose: true });
                        }
                        // 将实时请求列表中该请求的 channel 更新为新的上游，便于列表直观看到最终上游
                        {
                            const req = realtimeRequests.value.find(r => r.request_id === event.request_id);
                            if (req) {
                                req.channel = event.to_channel || req.channel;
                            }
                        }
                        if (isLoadbalanceWeightMode.value) {
                            loadLoadbalanceConfig().catch(() => {});
                        }
                        break;
                    case 'lb_reset':
                        if (loadbalanceOptions.notifyEnabled) {
                            const msg = `服务 [${event.service}] 一轮候选均失败，已重置失败计数并重试（共 ${event.total_configs} 个，阈值 ${event.threshold}）`;
                            ElMessage.info({ message: msg, duration: 3000, showClose: true });
                        }
                        if (isLoadbalanceWeightMode.value) {
                            loadLoadbalanceConfig().catch(() => {});
                        }
                        break;
                    case 'lb_exhausted':
                        if (loadbalanceOptions.notifyEnabled) {
                            const remaining = Number(event.cooldown_remaining_seconds ?? 0);
                            const msg = `服务 [${event.service}] 无可用上游：所有候选达到失败阈值 ${event.threshold}。` +
                                (remaining > 0
                                    ? ` 冷却剩余约 ${remaining} 秒，可手动重置或等待自动重置。`
                                    : ' 可手动重置或等待自动重置。');
                            ElMessage.error({ message: msg, duration: 4000, showClose: true });
                        }
                        if (isLoadbalanceWeightMode.value) {
                            loadLoadbalanceConfig().catch(() => {});
                        }
                        break;
                    case 'connection':
                        connectionStatus[event.service] = event.status === 'connected';
                        if (event.status === 'connected') {
                            console.log(`${event.service} 实时连接已建立`);
                        } else if (event.status === 'disconnected') {
                            console.log(`${event.service} 实时连接已断开`);
                        } else if (event.status === 'error') {
                            console.log(`${event.service} 实时连接错误:`, event.error);
                        }
                        break;

                    case 'snapshot':
                    case 'started':
                        addRealtimeRequest(event);
                        break;

                    case 'progress':
                        updateRequestProgress(event);
                        break;

                    case 'completed':
                    case 'failed':
                        completeRequest(event);
                        break;

                    default:
                }
            } catch (error) {
                console.error('处理实时事件失败:', error);
            }
        };

        const addRealtimeRequest = (event) => {
            try {
                const existingIndex = realtimeRequests.value.findIndex(r => r.request_id === event.request_id);

                if (existingIndex >= 0) {
                    // 更新现有请求
                    Object.assign(realtimeRequests.value[existingIndex], event);
                } else {
                    // 添加新请求
                    const request = {
                        ...event,
                        responseText: '',
                        displayDuration: event.duration_ms || 0
                    };

                    realtimeRequests.value.unshift(request);

                    // 保持最多显示指定数量的请求
                    if (realtimeRequests.value.length > maxRealtimeRequests) {
                        realtimeRequests.value = realtimeRequests.value.slice(0, maxRealtimeRequests);
                    }
                }
            } catch (error) {
                console.error('添加实时请求失败:', error);
            }
        };

        const updateRequestProgress = (event) => {
            try {
                const request = realtimeRequests.value.find(r => r.request_id === event.request_id);
                if (!request) return;

                // 更新状态和耗时
                if (event.status) {
                    request.status = event.status;
                }
                if (event.duration_ms !== undefined) {
                    request.displayDuration = event.duration_ms;
                }

                // 累积响应文本
                if (event.response_delta) {
                    request.responseText += event.response_delta;

                    // 如果详情抽屉开着且显示当前请求，自动滚动
                    if (realtimeDetailVisible.value &&
                        selectedRealtimeRequest.value?.request_id === event.request_id) {
                        nextTick(() => {
                            scrollResponseToBottom();
                        });
                    }
                }
            } catch (error) {
                console.error('更新请求进度失败:', error);
            }
        };

        const completeRequest = (event) => {
            try {
                const request = realtimeRequests.value.find(r => r.request_id === event.request_id);
                if (!request) return;

                request.status = event.status || (event.type === 'completed' ? 'COMPLETED' : 'FAILED');
                request.displayDuration = event.duration_ms || request.displayDuration;
                request.status_code = event.status_code;

                if (isLoadbalanceWeightMode.value) {
                    loadLoadbalanceConfig().catch(err => console.error('刷新负载均衡数据失败:', err));
                }
            } catch (error) {
                console.error('完成请求失败:', error);
            }
        };

        // UI辅助方法
        const formatRealtimeTime = (isoString) => {
            try {
                return new Date(isoString).toLocaleTimeString('zh-CN');
            } catch (error) {
                return isoString;
            }
        };

        const getStatusDisplay = (status) => {
            return REQUEST_STATUS[status] || { text: status, type: '' };
        };

        const showRealtimeDetail = (request) => {
            selectedRealtimeRequest.value = request;
            realtimeDetailVisible.value = true;
        };

        const scrollResponseToBottom = () => {
            try {
                const container = document.querySelector('.response-stream-content');
                if (container) {
                    container.scrollTop = container.scrollHeight;
                }
            } catch (error) {
                console.error('滚动响应内容失败:', error);
            }
        };

        const reconnectRealtime = () => {
            if (realtimeManager.value) {
                console.log('手动重连实时服务...');
                console.log('当前连接状态:', realtimeManager.value.getConnectionStatus());
                console.log('管理器状态:', realtimeManager.value.getStatus());

                realtimeManager.value.reconnectAll();
                ElMessage.info('正在重新连接实时服务...');
            }
        };

        const disconnectRealtime = () => {
            if (realtimeManager.value) {
                console.log('手动断开实时服务...');
                realtimeManager.value.disconnectAll();
                ElMessage.info('已断开实时服务连接');
            }
        };

        // 添加调试功能
        const checkConnectionStatus = () => {
            if (realtimeManager.value) {
                console.log('=== 连接状态调试信息 ===');
                console.log('连接状态:', realtimeManager.value.getConnectionStatus());
                console.log('管理器状态:', realtimeManager.value.getStatus());
                console.log('当前实时请求数量:', realtimeRequests.value.length);
                console.log('实时请求列表:', realtimeRequests.value);
                console.log('========================');
            }
        };

        // 暴露调试功能到全局
        window.debugRealtime = checkConnectionStatus;

        // 组件挂载
        onMounted(() => {
            loadData();
            // 初始化实时连接
            initRealTimeConnections();
            // 启动自动刷新
            startAutoRefresh();
        });
        
        // 组件卸载前清理定时器
        onBeforeUnmount(() => {
            stopAutoRefresh();
        });
        
        return {
            // 响应式数据
            loading,
            logsLoading,
            allLogsLoading,
            configSaving,
            filterSaving,
            lastUpdate,
            
            // 自动刷新相关
            autoRefreshCountdown,
            formatCountdown,
            
            services,
            stats,
            logs,
            allLogs,
            claudeConfigs,
            codexConfigs,
            configDrawerVisible,
            bodyFilterDrawerVisible,        // 重命名
            headerFilterDrawerVisible,      // 新增
            endpointFilterDrawerVisible,    // 新增
            logDetailVisible,
            logDetailLoading,
            logDetailError,
            allLogsVisible,
            activeConfigTab,
            activeLogTab,
            configContents,
            filterContent,
            filterRules,
            headerFilterConfig,             // 新增
            endpointFilterConfig,           // 新增
            headerFilterSaving,             // 新增
            selectedLog,
            decodedRequestBody,
            decodedOriginalRequestBody,
            usageSummary,
            usageDrawerVisible,
            usageDetails,
            usageDetailsLoading,
            usageMetricLabels,
            metricKeys,
            tokenServiceKeys,
            tokenServiceLabels,
            friendlyConfigs,
            configEditMode,
            editingNewSite,
            newSiteData,
            modelSelectorVisible,
            testResultVisible,
            testingConnection,
            testConfig,
            lastTestResult,
            newSiteTestResult,
            testResponseDialogVisible,
            testResponseData,

            // 方法
            refreshData,
            switchConfig,
            openConfigDrawer,
            closeConfigDrawer,
            saveConfig,
            openBodyFilterDrawer,           // 重命名
            closeBodyFilterDrawer,          // 重命名
            loadFilter,
            saveFilter,
            addFilterRule,
            removeFilterRule,
            openHeaderFilterDrawer,         // 新增
            closeHeaderFilterDrawer,        // 新增
            loadHeaderFilter,               // 新增
            saveHeaderFilter,               // 新增
            addBlockedHeader,               // 新增
            removeBlockedHeader,            // 新增
            applyHeaderPreset,              // 新增
            openEndpointFilterDrawer,       // 新增
            closeEndpointFilterDrawer,      // 新增
            loadEndpointFilter,             // 新增
            saveEndpointFilter,             // 新增
            addEndpointRule,                // 新增
            removeEndpointRule,             // 新增
            addQueryPair,                   // 新增
            removeQueryPair,                // 新增
            HTTP_METHOD_OPTIONS,            // 新增
            formatTimestamp,
            truncatePath,
            getStatusTagType,
            getFilteredHeaders,         // 新增
            showLogDetail,
            viewAllLogs,
            refreshAllLogs,
            clearAllLogs,
            copyToClipboard,
            formatFilteredRequestBody,
            formatOriginalRequestBody,
            formatResponseContent,
            decodedResponseContent,
            formatUsageValue,
            formatUsageSummary,
            getUsageFormattedValue,
            hasUsageData,
            formatChannelName,
            formatServiceWithChannel,
            formatMethodWithURL,
            openUsageDrawer,
            closeUsageDrawer,
            clearUsageData,
            loadUsageDetails,
            getSortedHeaderKeys,
            startAddingSite,
            confirmAddSite,
            cancelAddSite,
            saveInteractiveConfig,
            removeConfigSite,
            handleActiveChange,
            handleDeletedChange,
            handleNewSiteDeletedChange,
            syncFormToJson,
            syncJsonToForm,
            getModelOptions,
            testNewSiteConnection,
            testSiteConnection,
            showModelSelector,
            cancelModelSelection,
            confirmModelSelection,
            copyTestResult,
            showTestResponse,
            testResponseDialogVisible,
            testResponseData,
            copyTestResponseData,

            // 实时请求相关
            realtimeRequests,
            realtimeDetailVisible,
            loadbalanceOptions,
            updateGlobalFailureThreshold,
            selectedRealtimeRequest,
            connectionStatus,
            formatRealtimeTime,
            getStatusDisplay,
            showRealtimeDetail,
            reconnectRealtime,
            disconnectRealtime,

            // 模型路由管理相关
            routingMode,
            routingConfig,
            routingConfigSaving,
            modelMappingDrawerVisible,
            configMappingDrawerVisible,
            activeModelMappingTab,
            activeConfigMappingTab,
            selectRoutingMode,
            getRoutingModeText,
            openModelMappingDrawer,
            openConfigMappingDrawer,
            closeModelMappingDrawer,
            closeConfigMappingDrawer,
            addModelMapping,
            removeModelMapping,
            addConfigMapping,
            removeConfigMapping,
            saveRoutingConfig,
            loadRoutingConfig,

            // 负载均衡相关
            loadbalanceConfig,
            loadbalanceSaving,
            loadbalanceLoading,
            loadbalanceDisabledNotice,
            isLoadbalanceWeightMode,
            weightedTargets,
            selectLoadbalanceMode,
            saveLoadbalanceConfig,
            resetLoadbalanceFailures,
            resettingFailures
        };
    }
});

// 检查Element Plus是否正确加载
console.log('ElementPlus对象:', ElementPlus);
console.log('ElementPlus.version:', ElementPlus.version);

// 使用Element Plus - 包括所有组件和指令
try {
    app.use(ElementPlus);
    console.log('Element Plus 配置成功');
} catch (error) {
    console.error('Element Plus 配置失败:', error);
}

// 挂载应用
app.mount('#app');

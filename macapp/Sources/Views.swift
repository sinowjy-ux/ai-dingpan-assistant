import SwiftUI

// MARK: - 通用样式

struct Panel: ViewModifier {
    var glow: Color? = nil
    func body(content: Content) -> some View {
        content
            .background(RoundedRectangle(cornerRadius: 12).fill(Theme.panel))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(glow ?? Theme.line, lineWidth: glow == nil ? 1 : 1.5))
            .fxShadow(color: (glow ?? .clear).opacity(0.35), radius: glow == nil ? 0 : 10)
    }
}
extension View {
    func panel(glow: Color? = nil) -> some View { modifier(Panel(glow: glow)) }
}

let mono = Font.system(size: 12, design: .monospaced)
func monoF(_ s: CGFloat, _ w: Font.Weight = .regular) -> Font { .system(size: s, weight: w, design: .monospaced) }

struct SectionTitle: View {
    let text: String
    var trailing: String? = nil
    var trailingColor: Color = Theme.dim
    var body: some View {
        HStack {
            Text(text).font(monoF(11)).foregroundColor(Theme.dim)
            Spacer()
            if let t = trailing { Text(t).font(monoF(11, .medium)).foregroundColor(trailingColor) }
        }
    }
}

struct Bar: View {
    let value: Double
    let color: Color
    var height: CGFloat = 5
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.line)
                Capsule().fill(color).frame(width: max(0, min(1, value)) * g.size.width)
            }
        }
        .frame(height: height)
    }
}

struct Pill: View {
    let text: String
    let color: Color
    var filled = false
    var body: some View {
        Text(text).font(.system(size: 11.5, weight: .semibold))
            .padding(.horizontal, 8).padding(.vertical, 3)
            .foregroundColor(color)
            .background(RoundedRectangle(cornerRadius: 5).fill(color.opacity(filled ? 0.16 : 0.08)))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(color.opacity(0.7), lineWidth: 1))
    }
}

struct IconSquare: View {
    let char: String
    let color: Color
    var size: CGFloat = 30
    var body: some View {
        Text(char).font(.system(size: size * 0.5, weight: .bold)).foregroundColor(color)
            .frame(width: size, height: size)
            .background(RoundedRectangle(cornerRadius: 7).fill(color.opacity(0.14)))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(color.opacity(0.8), lineWidth: 1.2))
    }
}

// MARK: - 根视图

struct RootView: View {
    @EnvironmentObject var s: Store
    @EnvironmentObject var j: JournalModel
    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            if s.booting { BootView() } else if s.page != .monitor {
                VStack(spacing: 10) {
                    TopStrip()
                    switch s.page {
                    case .dashboard: DashboardPage()
                    case .review: ReviewPage()
                    case .stock: StockPage()
                    default: ScreenerPage()
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 12).padding(.top, 6)
                .ignoresSafeArea(edges: .top)
            } else {
                VStack(spacing: 10) {
                    TopStrip()
                    HeaderPanel()
                    HStack(alignment: .top, spacing: 12) {
                        VStack(spacing: 10) { ForEach(s.order, id: \.self) { StrategyCard(k: $0) } }
                            .frame(width: 292)
                        VStack(spacing: 10) {
                            FlowPanel()
                            HStack(alignment: .top, spacing: 12) {
                                FactorPanel()
                                RunLogPanel()
                            }
                            .frame(maxHeight: .infinity)
                            ScorePanel()
                        }
                        VStack(spacing: 10) {
                            HitBoard().frame(maxHeight: .infinity).layoutPriority(1)
                            StreamPanel().frame(height: 250)
                        }
                        .frame(width: 430)
                    }
                    Footer()
                }
                .padding(.horizontal, 16).padding(.bottom, 12).padding(.top, 6)
                .ignoresSafeArea(edges: .top)
                .overlay { if s.mode == .replay && !s.datasetReady { DatasetPrompt() } }
                .overlay(alignment: .top) { if let t = s.toast { HitToast(sig: t).padding(.top, 52).transition(.move(edge: .top).combined(with: .opacity)) } }
                .animation(.spring(response: 0.35, dampingFraction: 0.8), value: s.toast?.id)
            }
        }
        .overlay(alignment: .bottom) { if let t = j.toast { JournalToast(text: t).padding(.bottom, 28).transition(.opacity) } }
        .animation(.easeOut(duration: 0.25), value: j.toast)
        .alert("使用前请阅读", isPresented: $s.showDisclaimer) {
            Button("我已了解，继续使用") { UserDefaults.standard.set(true, forKey: "disclaimer_v1") }
        } message: {
            Text(DISCLAIMER)
        }
        .onAppear { Appearance.apply(s.appearance) }
        .foregroundColor(Theme.ink)
    }
}

struct BootView: View {
    @EnvironmentObject var s: Store
    var body: some View {
        VStack(spacing: 14) {
            Text(">_").font(monoF(40, .bold)).foregroundColor(Theme.green)
            if let e = s.bootError {
                Text("启动失败").font(.title3.bold())
                Text(e).font(mono).foregroundColor(Theme.red).multilineTextAlignment(.center).frame(maxWidth: 520)
                Button("重试") { s.bootError = nil; Task { await s.boot() } }
            } else {
                ProgressView().controlSize(.small)
                Text("正在启动盯盘引擎…").foregroundColor(Theme.dim)
            }
        }
    }
}

// MARK: - 顶部

struct TopStrip: View {
    @EnvironmentObject var s: Store
    var body: some View {
        HStack(spacing: 10) {
            Picker("", selection: Binding(get: { s.page }, set: { s.page = $0 })) {
                Text("统计").tag(Page.dashboard)
                Text("每日复盘").tag(Page.review)
                Text("AI 盯盘").tag(Page.monitor)
                Text("主力选股").tag(Page.screener)
                Text("个股研判").tag(Page.stock)
            }
            .pickerStyle(.segmented).labelsHidden().frame(width: 420)
            if s.page == .monitor {
                Picker("", selection: Binding(get: { s.market }, set: { s.setMarket($0) })) {
                    Text("A股").tag("cn"); Text("美股").tag("us")
                }
                .pickerStyle(.segmented).labelsHidden().frame(width: 104)
                Picker("", selection: Binding(get: { s.n }, set: { s.setSize($0) })) {
                    ForEach(SIZES, id: \.0) { Text($0.1).tag($0.0) }
                }
                .labelsHidden().frame(width: 104).help("股票池：按成交额从大到小")
            }
            Spacer(minLength: 8)
            if s.page == .monitor { ControlBar() }
            Picker("", selection: Binding(get: { s.appearance }, set: { s.setAppearance($0) })) {
                Text("深色").tag("dark"); Text("浅色").tag("light"); Text("跟随系统").tag("system")
            }
            .labelsHidden().frame(width: 92).help("界面颜色")
        }
        .padding(.leading, 74)   // 给红绿灯按钮留位置
        .frame(height: 34)
    }
}

struct HeaderPanel: View {
    @EnvironmentObject var s: Store
    var statusText: String {
        if s.mode == .live {
            let m = ["idle": "未启动", "waiting": "等待开盘", "loading": "补算中", "running": "盯盘中", "lunch": "午间休市",
                     "done": "已收工", "stopped": "已停止", "error": "出错"]
            return "\(m[s.live?.status ?? "idle"] ?? "未启动") · \(s.market == "us" ? "纽约" : "北京")时间 \(s.live?.local_time ?? s.live?.cn_time ?? "--:--")"
        }
        if s.replay == nil { return "待命 · 选好交易日后开始回放" }
        return "\(s.finished ? "已收工" : (s.playing ? "回放中" : "已暂停")) · \(fmtT(s.clockT)) · \(s.replay!.date)"
    }
    var statusColor: Color {
        if s.mode == .live { return s.liveActive ? Theme.green : Theme.dim }
        return s.replay == nil ? Theme.dim : (s.playing || s.finished ? Theme.green : Theme.yellow)
    }
    var pill: String {
        if s.finished { return "六套策略全部跑完 · 信号 \(s.passed.count) 条" }
        if let k = s.activeKey { return "\(s.name(k)) · 扫描中 · 候选 \(grouped(s.stockCount))" }
        return "六套策略待命 · 候选 \(grouped(s.stockCount))"
    }
    var body: some View {
        HStack(spacing: 18) {
            Text(">_").font(monoF(26, .bold)).foregroundColor(Theme.green)
                .frame(width: 60, height: 60)
                .background(RoundedRectangle(cornerRadius: 14).fill(Theme.green.opacity(0.06)))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.green.opacity(0.85), lineWidth: 1.5))
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 10) {
                    Text("AI 盯盘助手").font(.system(size: 24, weight: .semibold))
                    Pill(text: "\(s.marketName) · \(s.n == 0 ? "全市场" : "前") \(grouped(s.meta?.stocks ?? 0)) 只", color: Theme.green)
                }
                HStack(spacing: 6) {
                    Circle().fill(statusColor).frame(width: 7, height: 7)
                    Text(statusText).font(.system(size: 13)).foregroundColor(Theme.ink.opacity(0.85))
                }
                HStack(spacing: 10) {
                    Pill(text: pill, color: s.activeKey.map { s.color($0) } ?? Theme.green, filled: true)
                    Text("规则引擎 · 没有依据，不出信号").font(.system(size: 11.5)).foregroundColor(Theme.faint)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(grouped(s.scanned)).font(.system(size: 46, weight: .bold, design: .monospaced))
                    .contentTransition(.numericText()).lineLimit(1).minimumScaleFactor(0.5)
                Text("今日累计扫描 · 只次 · 逐分钟真实分时").font(.system(size: 11.5)).foregroundColor(Theme.dim)
                Text("候选 \(grouped(s.stockCount)) × 6 套策略").font(.system(size: 12.5, weight: .semibold))
            }
            .frame(minWidth: 300, alignment: .trailing)
            Rectangle().fill(Theme.line).frame(width: 1, height: 74)
            VStack(alignment: .leading, spacing: 4) {
                stat("信号", "\(s.passed.count)", Theme.ink)
                stat("共振", "\(s.resonance.count)", Theme.green)
                stat("剔除", grouped(s.cut), Theme.red)
                indexRow
            }
            .frame(width: 210)
        }
        .padding(.horizontal, 16).padding(.vertical, 12).panel()
    }
    func stat(_ k: String, _ v: String, _ c: Color) -> some View {
        HStack {
            Text(k).font(.system(size: 12.5)).foregroundColor(Theme.dim)
            Spacer()
            Text(v).font(monoF(18, .semibold)).foregroundColor(c).contentTransition(.numericText())
        }
    }
    @ViewBuilder var indexRow: some View {
        HStack {
            Text(s.indexName).font(.system(size: 12.5)).foregroundColor(Theme.dim)
            Spacer()
            if let n = s.indexNow, let p = s.indexPrev, p > 0 {
                Text(String(format: "%.0f", n)).font(monoF(13, .medium))
                Text(signed((n / p - 1) * 100)).font(monoF(12)).foregroundColor(Theme.up(n - p))
            } else { Text("—").font(monoF(13)).foregroundColor(Theme.dim) }
        }
    }
}

// MARK: - 控制条

struct ControlBar: View {
    @EnvironmentObject var s: Store
    var body: some View {
        HStack(spacing: 14) {
            Picker("", selection: Binding(get: { s.mode }, set: { $0 == .live ? s.enterLive() : s.enterReplay() })) {
                Text("回放复盘").tag(Mode.replay)
                Text("实时盯盘").tag(Mode.live)
            }
            .pickerStyle(.segmented).frame(width: 150).labelsHidden()

            if s.mode == .replay { replayControls } else { liveControls }
        }
        .controlSize(.regular)
    }

    @ViewBuilder var replayControls: some View {
        Picker("交易日", selection: $s.date) { ForEach((s.meta?.dates ?? []).reversed(), id: \.self) { Text($0).tag($0) } }
            .labelsHidden().frame(width: 116).help("交易日（近 5 个）")
        Picker("时段", selection: $s.window) { ForEach(s.windows) { Text($0.label).tag($0) } }
            .labelsHidden().frame(width: 150).help("回放时段")
        Picker("速度", selection: $s.speedIdx) { ForEach(0..<SPEEDS.count, id: \.self) { Text(SPEEDS[$0].0).tag($0) } }
            .labelsHidden().frame(width: 108).help("回放速度")
        Button { s.toggle() } label: {
            Label(s.loading ? "计算中" : (s.replay == nil || s.finished ? (s.finished ? "重新回放" : "开始回放") : (s.playing ? "暂停" : "继续")),
                  systemImage: s.playing ? "pause.fill" : (s.finished ? "arrow.counterclockwise" : "play.fill"))
                .frame(minWidth: 70)
        }
        .buttonStyle(.borderedProminent).tint(Theme.green.opacity(0.85)).disabled(s.loading || !s.datasetReady)
        .keyboardShortcut(.space, modifiers: [])
        Button("跳到结尾") { s.skipToEnd() }.disabled(s.replay == nil || s.finished)
        SaveReplayButton()
    }

    @ViewBuilder var liveControls: some View {
        Button { Task { s.liveActive ? await s.stopLive() : await s.startLive() } } label: {
            Label(s.liveActive ? "停止盯盘" : "开始盯盘", systemImage: s.liveActive ? "stop.fill" : "dot.radiowaves.left.and.right")
                .frame(minWidth: 96)
        }
        .buttonStyle(.borderedProminent).tint(s.liveActive ? Theme.red.opacity(0.8) : Theme.green.opacity(0.85))
        Toggle("命中弹系统通知", isOn: Binding(get: { s.live?.notify ?? true }, set: { v in Task { await s.setNotify(v) } }))
            .toggleStyle(.checkbox)
        Text(phaseText).font(.system(size: 11.5)).foregroundColor(Theme.dim).lineLimit(1)
    }
    var phaseText: String {
        let p = ["open": "交易中", "lunch": "午间休市", "pre": "盘前", "closed": "已收盘"][s.live?.phase ?? ""] ?? ""
        let poll = s.live?.last_poll.map { " · 上次刷新 \($0)" } ?? ""
        return "\(p)\(poll)"
    }
}

// MARK: - 左侧：六套策略

struct StrategyCard: View {
    @EnvironmentObject var s: Store
    let k: String
    var body: some View {
        let c = s.card(k)
        let color = s.color(k)
        let st = s.status(k)
        let sig = s.signals(of: k)
        let ok = sig.filter { $0.grade != "C" }
        let head = HStack(spacing: 9) {
            IconSquare(char: c?.char ?? "?", color: color, size: 28)
            Text(s.name(k)).font(.system(size: 15.5, weight: .semibold)).lineLimit(1)
            Text(c?.en ?? "").font(monoF(8.5)).foregroundColor(Theme.faint).lineLimit(1)
            Spacer(minLength: 0)
            StatusBadge(st: st, color: color)
        }
        let best = ok.max(by: { $0.score < $1.score })
        let stats = Text(st == .idle ? "等待 \(fmtT(c?.window.first ?? 930)) 开工" :
                         "剔除 \(sig.count - ok.count) · 信号 \(ok.count)" + (best.map { " · 最佳 \($0.name) \($0.score)" } ?? ""))
            .font(.system(size: 11.5)).foregroundColor(Theme.dim).lineLimit(1)
        let foot = HStack(spacing: 8) {
            Text("已处理").font(.system(size: 11)).foregroundColor(Theme.dim)
            Text(grouped(processed(st))).font(monoF(11.5, .semibold)).frame(minWidth: 62, alignment: .leading)
            Bar(value: s.progress(k), color: color, height: 4)
        }
        ViewThatFits(in: .vertical) {
            VStack(alignment: .leading, spacing: 4) {
                head
                Text(c?.tag ?? "").font(.system(size: 12)).foregroundColor(Theme.ink.opacity(0.8))
                Text(c?.rule ?? "").font(.system(size: 12, weight: .medium)).foregroundColor(color)
                stats
                Spacer(minLength: 0)
                foot
            }
            VStack(alignment: .leading, spacing: 4) {
                head
                Text(c?.rule ?? "").font(.system(size: 12, weight: .medium)).foregroundColor(color).lineLimit(1)
                stats
                Spacer(minLength: 0)
                foot
            }
            VStack(alignment: .leading, spacing: 3) { head; stats; foot }
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .panel(glow: s.activeKey == k && st == .scanning ? color : nil)
        .animation(.easeOut(duration: 0.25), value: st)
    }
    func processed(_ st: StratStatus) -> Int {
        guard let w = s.card(k)?.window, st != .idle else { return 0 }
        let n = Int((s.progress(k) * Double(s.mIdx(w[1]) - s.mIdx(w[0]) + 1)).rounded())
        return n * s.stockCount
    }
}

struct StatusBadge: View {
    let st: StratStatus
    let color: Color
    var body: some View {
        switch st {
        case .idle: Pill(text: "待命", color: Theme.faint)
        case .scanning: Pill(text: "扫描中", color: color, filled: true)
        case .done: Pill(text: "完工", color: Theme.green)
        }
    }
}

// MARK: - 中间：流水线

struct FlowPanel: View {
    @EnvironmentObject var s: Store
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            SectionTitle(text: "LIVE FLOW · " + s.order.compactMap { s.card($0)?.char }.joined(separator: " → "),
                         trailing: s.mode == .live ? "实时" : (s.replay == nil ? "待命" : fmtT(s.clockT)),
                         trailingColor: Theme.green)
            HStack(spacing: 10) {
                let last = Array(s.passed.suffix(4).reversed())
                ForEach(0..<4, id: \.self) { i in
                    if i < last.count { MiniSignal(sig: last[i]) } else { MiniEmpty() }
                }
            }
            HStack(spacing: 0) {
                ForEach(Array(s.order.enumerated()), id: \.element) { i, k in
                    if i > 0 {
                        Line().stroke(style: StrokeStyle(lineWidth: 1, dash: [3, 3])).foregroundColor(Theme.faint)
                            .frame(height: 1).padding(.bottom, 30)
                    }
                    FlowNode(k: k)
                }
            }
            HStack(spacing: 10) {
                Tile(title: "股票池", value: grouped(s.meta?.stocks ?? 0), note: "近 20 日成交额前列", color: Theme.blue)
                Tile(title: "候选", value: grouped(s.stockCount), note: "有昨收与日线背景", color: Theme.yellow)
                Tile(title: "纪律剔除", value: grouped(s.cut), note: "纪律分 < 60 不采纳", color: Theme.red)
                Tile(title: "日志", value: "第 \(s.logs.count) 行", note: "每一步都有记录", color: Theme.green)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 11).panel()
    }
}

struct Line: Shape {
    func path(in r: CGRect) -> Path { var p = Path(); p.move(to: CGPoint(x: 0, y: r.midY)); p.addLine(to: CGPoint(x: r.maxX, y: r.midY)); return p }
}

struct MiniSignal: View {
    @EnvironmentObject var s: Store
    let sig: Signal
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(sig.name).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                Spacer(minLength: 2)
                Circle().fill(s.color(sig.strategy)).frame(width: 6, height: 6)
            }
            Text("\(sig.strategy_name) · \(sig.score)").font(.system(size: 11)).foregroundColor(s.color(sig.strategy)).lineLimit(1)
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.panel2))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(s.color(sig.strategy).opacity(0.35)))
        .onTapGesture { s.selectedID = sig.id }
    }
}

struct MiniEmpty: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("···").font(.system(size: 13)).foregroundColor(Theme.faint)
            Text("等待信号").font(.system(size: 11)).foregroundColor(Theme.faint)
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).stroke(Theme.line))
    }
}

struct FlowNode: View {
    @EnvironmentObject var s: Store
    let k: String
    var body: some View {
        let st = s.status(k)
        let color = s.color(k)
        let active = s.activeKey == k && st == .scanning
        VStack(spacing: 5) {
            Text(s.card(k)?.char ?? "").font(.system(size: 17, weight: .bold))
                .foregroundColor(st == .idle ? Theme.dim : Theme.ink)
                .frame(width: 44, height: 44)
                .background(Circle().fill(st == .idle ? Theme.panel2 : color.opacity(active ? 0.55 : 0.28)))
                .overlay(Circle().stroke(st == .idle ? Theme.line : color, lineWidth: active ? 2 : 1.2))
                .fxShadow(color: active ? color.opacity(0.7) : .clear, radius: 10)
                .scaleEffect(active ? 1.08 : 1)
                .animation(.easeOut(duration: 0.3), value: active)
            Text(s.name(k)).font(.system(size: 10.5, weight: .medium)).foregroundColor(color).lineLimit(1).fixedSize()
            Text("信号 \(s.signals(of: k).filter { $0.grade != "C" }.count)").font(monoF(10)).foregroundColor(Theme.dim)
        }
        .frame(width: 84)
    }
}

struct Tile: View {
    let title: String, value: String, note: String, color: Color
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 10.5, weight: .medium)).foregroundColor(color)
            Text(value).font(monoF(19, .semibold)).lineLimit(1).minimumScaleFactor(0.6).contentTransition(.numericText())
            Text(note).font(.system(size: 9.5)).foregroundColor(Theme.faint).lineLimit(1)
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.panel2))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.line))
    }
}

// MARK: - 中间：纪律拆分

struct FactorPanel: View {
    @EnvironmentObject var s: Store
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "当前标的 · 纪律拆分", trailing: s.mode == .live ? "LIVE" : "REPLAY", trailingColor: Theme.green)
            if let sig = s.selected {
                HStack(spacing: 8) {
                    Text(sig.name).font(.system(size: 19, weight: .semibold))
                    Text(sig.code).font(monoF(11)).foregroundColor(Theme.dim)
                    Pill(text: sig.strategy_name, color: s.color(sig.strategy))
                    Spacer()
                    Text(sig.time).font(monoF(11)).foregroundColor(Theme.dim)
                }
                VStack(spacing: 3) {
                    ForEach(sig.checks, id: \.name) { c in
                        HStack(spacing: 8) {
                            Text(c.name).font(.system(size: 11.5)).foregroundColor(Theme.ink.opacity(0.85)).frame(width: 56, alignment: .leading)
                            Bar(value: c.ok ? 1 : 0.0, color: c.ok ? s.color(sig.strategy) : Theme.red.opacity(0.5), height: 6)
                                .overlay(alignment: .leading) { if !c.ok { Capsule().stroke(Theme.red.opacity(0.4)).frame(height: 6) } }
                                .help(c.note)
                            Text("\(c.ok ? c.pts : 0)/\(c.pts)").font(monoF(11)).foregroundColor(c.ok ? Theme.ink : Theme.red).frame(width: 40, alignment: .trailing)
                        }
                    }
                }
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("纪律分").font(.system(size: 12)).foregroundColor(Theme.dim)
                    Text("\(sig.score)").font(monoF(20, .bold)).foregroundColor(Theme.grade(sig.grade))
                    Text("\(sig.grade) · \(sig.verdict)").font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.grade(sig.grade))
                    Spacer()
                    Text("止损 \(String(format: "%.2f", sig.stop)) · 风险 \(String(format: "%.1f", sig.risk))%").font(monoF(11)).foregroundColor(Theme.dim)
                }
                Text(sig.reason).font(.system(size: 11.5)).foregroundColor(Theme.dim).lineLimit(1).help(sig.reason)
                MiniChart(sig: sig).frame(maxHeight: .infinity)
            } else {
                Spacer()
                Text("等待第一条信号…").foregroundColor(Theme.dim).frame(maxWidth: .infinity)
                Spacer()
            }
        }
        .padding(14).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).panel()
        .task(id: s.selected?.id) { if let sig = s.selected { await s.loadSeries(for: sig) } }
    }
}

struct MiniChart: View {
    @EnvironmentObject var s: Store
    let sig: Signal
    var body: some View {
        let mins = s.minutes
        let dd = s.seriesFor(sig)
        let limitT = (s.mode == .replay && !s.finished) ? s.clockT : 2400
        let lineColor = s.color(sig.strategy)
        Canvas { ctx, size in
            guard let d = dd, !d.t.isEmpty else { return }
            let n = d.t.filter { $0 <= limitT }.count
            guard n > 1 else { return }
            var vals = Array(d.p[0..<n]) + Array(d.v[0..<n]) + [sig.stop]
            if let pc = d.pc { vals.append(pc) }
            let lo = vals.min()!, hi = vals.max()!, pad = max((hi - lo) * 0.1, 0.01)
            func x(_ t: Int) -> CGFloat { CGFloat(indexIn(mins, t)) / CGFloat(max(mins.count - 1, 1)) * size.width }
            func y(_ v: Double) -> CGFloat { size.height - CGFloat((v - lo + pad) / (hi - lo + 2 * pad)) * size.height }
            if let pc = d.pc {
                var p = Path(); p.move(to: CGPoint(x: 0, y: y(pc))); p.addLine(to: CGPoint(x: size.width, y: y(pc)))
                ctx.stroke(p, with: .color(Theme.faint), style: StrokeStyle(lineWidth: 1, dash: [2, 3]))
            }
            var stop = Path(); stop.move(to: CGPoint(x: x(sig.t), y: y(sig.stop))); stop.addLine(to: CGPoint(x: size.width, y: y(sig.stop)))
            ctx.stroke(stop, with: .color(Theme.red.opacity(0.7)), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
            var vw = Path(), pr = Path()
            for i in 0..<n {
                let a = CGPoint(x: x(d.t[i]), y: y(d.v[i])), b = CGPoint(x: x(d.t[i]), y: y(d.p[i]))
                if i == 0 { vw.move(to: a); pr.move(to: b) } else { vw.addLine(to: a); pr.addLine(to: b) }
            }
            ctx.stroke(vw, with: .color(Theme.yellow.opacity(0.8)), style: StrokeStyle(lineWidth: 1.2, dash: [4, 3]))
            ctx.stroke(pr, with: .color(lineColor), lineWidth: 1.6)
            let dot = CGRect(x: x(sig.t) - 4, y: y(sig.price) - 4, width: 8, height: 8)
            ctx.fill(Path(ellipseIn: dot), with: .color(Theme.red))
            ctx.stroke(Path(ellipseIn: dot.insetBy(dx: -2, dy: -2)), with: .color(Theme.red.opacity(0.4)), lineWidth: 1)
        }
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.panel2))
        .overlay(alignment: .bottomLeading) {
            HStack(spacing: 10) {
                Text("— 价格").foregroundColor(s.color(sig.strategy))
                Text("- - 分时均价").foregroundColor(Theme.yellow)
                Text("- - 止损").foregroundColor(Theme.red)
            }
            .font(.system(size: 9.5)).padding(6)
        }
        .frame(minHeight: 34)
    }
}

// MARK: - 中间：运行日志

struct RunLogPanel: View {
    @EnvironmentObject var s: Store
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("$ tail -f run.log").font(monoF(12.5, .semibold)).foregroundColor(Theme.green)
                Spacer()
                Text("\(s.logs.count) 行").font(monoF(11)).foregroundColor(Theme.dim)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 3) {
                        ForEach(s.logs) { l in
                            HStack(alignment: .top, spacing: 8) {
                                Text(l.time).foregroundColor(Theme.faint)
                                Text(l.text).foregroundColor(color(l)).lineLimit(1)
                            }
                            .font(monoF(11.5))
                            .id(l.id)
                        }
                        TimelineView(.periodic(from: .now, by: 0.55)) { tl in
                            Rectangle().fill(Theme.green).frame(width: 7, height: 13)
                                .opacity(Int(tl.date.timeIntervalSince1970 / 0.55) % 2 == 0 ? 1 : 0.15)
                        }.id("cursor")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: s.logs.count) { _ in proxy.scrollTo("cursor", anchor: .bottom) }
            }
        }
        .padding(14).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).panel()
    }
    func color(_ l: LogLine) -> Color {
        switch l.kind {
        case .signal: return l.color ?? Theme.green
        case .cut: return Theme.red.opacity(0.75)
        case .start, .done: return l.color ?? Theme.ink
        case .warn: return Theme.yellow
        case .info: return Theme.ink.opacity(0.75)
        }
    }
}

// MARK: - 中间：战绩 + 信号曲线

struct ScorePanel: View {
    @EnvironmentObject var s: Store
    var range: (Int, Int) {
        if s.mode == .live { return (930, 1500) }
        return (s.window.start, s.window.end)
    }
    var body: some View {
        HStack(spacing: 18) {
            VStack(alignment: .leading, spacing: 5) {
                SectionTitle(text: "今日战绩 · 开盘 vs 现在")
                HStack { Text("开工").foregroundColor(Theme.dim); Spacer(); Text("0 条").font(monoF(14, .semibold)) }
                HStack(alignment: .firstTextBaseline) {
                    Text("现在").foregroundColor(Theme.dim); Spacer()
                    Text("\(s.passed.count) 条信号").font(.system(size: 22, weight: .bold)).foregroundColor(Theme.green)
                        .contentTransition(.numericText())
                }
                Bar(value: Double(s.mIdx(s.clockT) - s.mIdx(range.0) + 1) / Double(s.mIdx(range.1) - s.mIdx(range.0) + 1) * (s.replay == nil && s.mode == .replay ? 0 : 1), color: Theme.green, height: 5)
                HStack {
                    Text("已扫描 \(grouped(s.scanned))").foregroundColor(Theme.dim)
                    Spacer()
                    Text("共振 \(s.resonance.count)").foregroundColor(Theme.dim)
                }
                .font(.system(size: 11.5))
                if s.finished, let line = afterLine { Text(line).font(.system(size: 11)).foregroundColor(Theme.dim).lineLimit(2) }
            }
            .frame(width: 270)
            VStack(alignment: .leading, spacing: 6) {
                SectionTitle(text: "信号曲线", trailing: "\(fmtT(range.0)) → \(fmtT(range.1))")
                StepChart(points: curve, total: s.mIdx(range.1) - s.mIdx(range.0) + 1)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 10).frame(height: 124).panel()
    }
    /// 每分钟累计可执行+观察信号数
    var curve: [Int] {
        guard s.mode == .live || s.replay != nil else { return [] }
        let a = s.mIdx(range.0), c = s.mIdx(s.clockT)
        guard c >= a else { return [] }
        let ts = s.passed.map { s.mIdx($0.t) }.sorted()
        var out: [Int] = [], j = 0
        for i in a...min(c, s.mIdx(range.1)) { while j < ts.count && ts[j] <= i { j += 1 }; out.append(j) }
        return out
    }
    var afterLine: String? {
        let a = s.passed.compactMap { $0.after?.close }
        guard !a.isEmpty else { return nil }
        let avg = a.reduce(0, +) / Double(a.count), win = Double(a.filter { $0 > 0 }.count) / Double(a.count) * 100
        return "复盘：信号价→收盘 平均 \(signed(avg))，收盘为正 \(Int(win))%（单日样本，仅供参考）"
    }
}

struct StepChart: View {
    let points: [Int]
    let total: Int
    var body: some View {
        Canvas { ctx, size in
            let maxV = max(points.max() ?? 0, 4)
            func x(_ i: Int) -> CGFloat { CGFloat(i) / CGFloat(max(total - 1, 1)) * size.width }
            func y(_ v: Int) -> CGFloat { size.height - 4 - CGFloat(v) / CGFloat(maxV) * (size.height - 12) }
            var grid = Path()
            for g in 1...3 { let yy = size.height * CGFloat(g) / 4; grid.move(to: CGPoint(x: 0, y: yy)); grid.addLine(to: CGPoint(x: size.width, y: yy)) }
            ctx.stroke(grid, with: .color(Theme.line), lineWidth: 0.5)
            guard points.count > 0 else { return }
            var p = Path(); p.move(to: CGPoint(x: 0, y: y(points[0])))
            for i in 1..<max(points.count, 1) where i < points.count {
                p.addLine(to: CGPoint(x: x(i), y: y(points[i - 1])))
                p.addLine(to: CGPoint(x: x(i), y: y(points[i])))
            }
            var fill = p
            fill.addLine(to: CGPoint(x: x(points.count - 1), y: size.height)); fill.addLine(to: CGPoint(x: 0, y: size.height)); fill.closeSubpath()
            ctx.fill(fill, with: .linearGradient(Gradient(colors: [Theme.green.opacity(0.28), Theme.green.opacity(0.02)]),
                                                startPoint: .zero, endPoint: CGPoint(x: 0, y: size.height)))
            ctx.stroke(p, with: .color(Theme.green), lineWidth: 1.8)
            let end = CGPoint(x: x(points.count - 1), y: y(points.last!))
            ctx.fill(Path(ellipseIn: CGRect(x: end.x - 7, y: end.y - 7, width: 14, height: 14)), with: .color(Theme.green.opacity(0.25)))
            ctx.fill(Path(ellipseIn: CGRect(x: end.x - 3.5, y: end.y - 3.5, width: 7, height: 7)), with: .color(.white))
        }
    }
}

// MARK: - 右侧：事件日志

struct EventRow: View {
    @EnvironmentObject var s: Store
    let sig: Signal
    var body: some View {
        let sel = s.selected?.id == sig.id
        let c = s.color(sig.strategy)
        HStack(spacing: 10) {
            Text(sig.time).font(monoF(12)).foregroundColor(Theme.dim)
            Text(sig.grade == "C" ? "剔除" : "命中").font(.system(size: 11, weight: .bold))
                .foregroundColor(sig.grade == "C" ? Theme.faint : c)
                .padding(.horizontal, 7).padding(.vertical, 3)
                .overlay(RoundedRectangle(cornerRadius: 5).stroke((sig.grade == "C" ? Theme.faint : c).opacity(0.8)))
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    Text(sig.name).font(.system(size: 13.5, weight: .semibold)).lineLimit(1)
                    Text("· \(sig.strategy_name)").font(.system(size: 13)).foregroundColor(Theme.ink.opacity(0.8)).lineLimit(1)
                    if sig.backfill == true { Text("补算").font(.system(size: 9.5)).foregroundColor(Theme.dim) }
                }
                Text("依据 · 量比 \(String(format: "%.1f", sig.lb)) · 涨 \(signed(sig.chg, 1)) · 止损距 \(String(format: "%.1f", sig.risk))%")
                    .font(.system(size: 10.5)).foregroundColor(Theme.dim).lineLimit(1)
            }
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 2) {
                Text("\(sig.score) 分").font(monoF(14, .semibold)).foregroundColor(Theme.grade(sig.grade))
                if s.finished, let a = sig.after {
                    Text("收 \(signed(a.close, 1))").font(monoF(10)).foregroundColor(Theme.up(a.close))
                } else {
                    Text(sig.verdict).font(.system(size: 10)).foregroundColor(Theme.grade(sig.grade).opacity(0.8))
                }
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 8).fill(sel ? c.opacity(0.10) : Theme.panel2.opacity(0.6)))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(sel ? c.opacity(0.6) : Color.clear))
        .contentShape(Rectangle())
        .onTapGesture { s.selectedID = sig.id }
        .opacity(sig.grade == "C" ? 0.72 : 1)
    }
}

// MARK: - 底部

struct Footer: View {
    @EnvironmentObject var s: Store
    var body: some View {
        HStack {
            Text("规则化策略输出 · 真实行情 · 非投资建议").font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.yellow)
                .padding(.horizontal, 14).padding(.vertical, 5)
                .background(RoundedRectangle(cornerRadius: 6).fill(Theme.yellow.opacity(0.08)))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.yellow.opacity(0.6)))
            if let e = s.errorText { Text(e).font(.system(size: 12)).foregroundColor(Theme.red).lineLimit(1) }
            Spacer()
            Text(s.dataset?.building == true ? (s.dataset?.log.last ?? "正在下载…") : (s.datasetReady ? "\(s.marketName) 分时 \(grouped(s.meta?.stocks ?? 0)) 只 · 更新于 \(s.meta?.built ?? "—")" : "\(s.marketName) \(s.sizeLabel) 未下载"))
                .font(.system(size: 11)).foregroundColor(Theme.dim)
            Button(s.dataset?.building == true ? "下载中…" : "更新数据") { Task { await s.download() } }
                .controlSize(.small).disabled(s.dataset?.building == true)
                .help("下载股票池近 5 个交易日的分时（约 2–3 分钟），收盘后点一次即可回放今天")
            Text("·").foregroundColor(Theme.faint)
            Text("\((s.mode == .live ? s.live?.date : s.replay?.date) ?? s.date) · frame \(String(format: "%04d", s.mode == .live ? (s.live?.polls ?? 0) : s.clockIdx))")
                .font(monoF(11)).foregroundColor(Theme.faint)
        }
    }
}


/// 把当前回放日的盯盘信号（含被剔除的）存进数据库，统计页可按天查、明天自动比对
struct SaveReplayButton: View {
    @EnvironmentObject var s: Store
    @EnvironmentObject var j: JournalModel
    var body: some View {
        Button { Task { await j.saveMonitor(date: s.replay?.date ?? s.date, market: s.market, n: s.n) } } label: {
            Label("存入数据库", systemImage: "tray.and.arrow.down")
        }
        .disabled(s.replay == nil || !s.datasetReady)
        .help("保存这一天的全部盯盘信号（命中与剔除都存，用来比对纪律分是否有效）")
    }
}


let DISCLAIMER = """
1. 本软件是个人编写的学习与研究工具，所有选股、盯盘信号都是规则的机械输出，不构成任何投资建议，不推荐任何具体股票。
2. 回测和实盘统计只反映历史，不代表未来收益。股市有风险，投资决策和盈亏由使用者自行负责。
3. 行情来自腾讯、新浪、东方财富、Yahoo、Nasdaq 等公开接口，可能延迟或出错，仅供个人学习使用，请勿商用或二次分发数据。
4. 软件免费、开源，作者不收费、不带单、不提供荐股服务。
5. 所有数据只保存在你自己的电脑上，不上传任何服务器。
"""

/// 录制演示视频时关闭模糊阴影（截图时阴影要逐帧重算，非常慢），平时使用不受影响
let FAST_FX = CommandLine.arguments.contains("--record")
extension View {
    func fxShadow(color: Color, radius: CGFloat, x: CGFloat = 0, y: CGFloat = 0) -> some View {
        shadow(color: FAST_FX ? .clear : color, radius: FAST_FX ? 0 : radius, x: x, y: y)
    }
}

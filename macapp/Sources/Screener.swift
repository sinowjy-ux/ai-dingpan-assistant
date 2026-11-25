import SwiftUI

// MARK: - 主力形态选股器（/api/screener）

struct ScrSignal: Codable, Identifiable, Hashable {
    let method: String
    let code: String
    let name: String
    let date: String
    let close: Double?
    let pct: Double?
    let score: Double
    let stop: Double?
    let entry_rule: String?
    let detail: [String]?
    let targets: [Double]?
    let flags: [String]?
    let days_ago: Int
    let last_close: Double?
    let chg_since: Double?
    let below_stop: Bool?
    let pe: Double?
    let turnover: Double?
    let resonance: [String]?
    let validated: Bool?
    let validation_note: String?
    var id: String { code + method + date }
}

struct ScrRegime: Codable { let date: String; let above_ma20: Bool }
struct ScrAlpha: Codable { let verdict: String? }
struct ScrBT: Codable { let alpha: [String: ScrAlpha]? }

struct ScanResult: Codable {
    let generated: String
    let data_date: String
    let quote_time: String?
    let days: Int
    let stocks: Int
    let count: Int
    let signals: [ScrSignal]
    let regime: ScrRegime?
    let backtest: ScrBT?
    let watch: [ScrWatch]?
}

struct ScrWatch: Codable, Identifiable, Hashable {
    let code: String, name: String, date: String
    let neck: Double, upper: Double, close: Double, to_upper: Double
    let waited: Int, left: Int, dd: Double
    let pe: Double?
    var id: String { code + date }
}

struct ScanStatus: Codable { let running: Bool; let started: String?; let exit: Int?; let log: String }

let SCR_METHODS = ["筹码峰突破", "箱体突破", "假跌破回升", "底部三K反转", "涨停换筹", "三波下跌反弹", "二次涨停", "看涨吞没"]
let SCR_COLORS: [String: String] = ["筹码峰突破": "#5B8DEF", "箱体突破": "#3CC48A", "假跌破回升": "#F08A3C", "底部三K反转": "#E8B931",
                                    "涨停换筹": "#A178F0", "三波下跌反弹": "#4FC3D9", "二次涨停": "#E8607A", "看涨吞没": "#9AA5B1"]

func beijingNow() -> Date { Date() }
func beijingString(_ fmt: String) -> String {
    let f = DateFormatter(); f.timeZone = TimeZone(identifier: "Asia/Shanghai"); f.locale = Locale(identifier: "zh_CN"); f.dateFormat = fmt
    return f.string(from: Date())
}
func cnTradingNow() -> Bool {
    var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "Asia/Shanghai")!
    let c = cal.dateComponents([.weekday, .hour, .minute], from: Date())
    let t = (c.hour ?? 0) * 100 + (c.minute ?? 0)
    guard let w = c.weekday, w != 1, w != 7 else { return false }
    return (930...1130).contains(t) || (1300...1500).contains(t)
}

@MainActor
final class ScreenerModel: ObservableObject {
    @Published var result: ScanResult?
    @Published var status: ScanStatus?
    @Published var error: String?
    @Published var methods: Set<String> = Set(SCR_METHODS)
    @Published var days = 0            // 0 = 仅最新交易日，2 = 近 3 日
    @Published var validatedOnly = false
    @Published var minScore = 0
    @Published var selectedID: String?
    @Published var autoRefresh = true
    @Published var showWatch = false      // 假跌破观察名单：已翻回颈线、等突破上颈线
    private var autoTask: Task<Void, Never>?
    private var lastAuto = Date.distantPast
    let api = Backend.shared

    func load() async {
        do { result = try await api.get("/api/screener", ScanResult.self); error = nil }
        catch { self.error = "还没有扫描结果，点“更新行情并扫描”" }
        if let st = try? await api.get("/api/screener/status", ScanStatus.self) { status = st; if st.running { await waitRun() } }
        startAuto()
    }

    func run() async {
        _ = try? await api.get("/api/screener/run", ScanStatus.self)
        await waitRun()
    }
    private func waitRun() async {
        while true {
            guard let st = try? await api.get("/api/screener/status", ScanStatus.self) else { break }
            status = st
            if !st.running { break }
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
        if let r = try? await api.get("/api/screener", ScanResult.self) { result = r; error = nil }
    }

    /// 盘中自动刷新：A股交易时段每 10 分钟重新拉实时行情并扫描（扫描本身约 1–2 分钟）
    func startAuto() {
        guard autoTask == nil else { return }
        autoTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                if self.autoRefresh && cnTradingNow() && self.status?.running != true && Date().timeIntervalSince(self.lastAuto) > 600 {
                    self.lastAuto = Date()
                    await self.run()
                }
                try? await Task.sleep(nanoseconds: 30_000_000_000)
            }
        }
    }

    var running: Bool { status?.running == true }
    var today: String { beijingString("yyyy-MM-dd") }
    var isFresh: Bool { result?.data_date == today }
    var freshness: (String, Color) {
        guard let r = result else { return ("没有数据", Theme.red) }
        if r.data_date == today { return (cnTradingNow() ? "盘中实时数据" : "今日最新数据", Theme.green) }
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let w = cal.component(.weekday, from: Date())
        if w == 1 || w == 7 { return ("最近交易日数据（今天休市）", Theme.yellow) }
        if beijingString("HHmm") < "0930" { return ("上一交易日数据（今天还未开盘）", Theme.yellow) }
        return ("不是今天的数据，请更新", Theme.red)
    }
    var verdicts: [String: String] {
        var m: [String: String] = [:]
        for (k, v) in result?.backtest?.alpha ?? [:] { m[k] = v.verdict ?? "" }
        return m
    }
    var rows: [ScrSignal] {
        (result?.signals ?? []).filter {
            methods.contains($0.method) && $0.days_ago <= days && Int($0.score) >= minScore && (!validatedOnly || $0.validated == true)
        }
    }
    func count(_ m: String) -> Int { (result?.signals ?? []).filter { $0.method == m && $0.days_ago <= days }.count }
    var selected: ScrSignal? { rows.first { $0.id == selectedID } ?? rows.first }
}

// MARK: - 页面

struct ScreenerPage: View {
    @EnvironmentObject var m: ScreenerModel
    var body: some View {
        VStack(spacing: 10) {
            ScrHeader()
            ScrFilters()
            HStack(alignment: .top, spacing: 12) {
                ScrList()
                ScrDetail().frame(width: 440)
            }
        }
        .task { await m.load() }
    }
}

struct ScrHeader: View {
    @EnvironmentObject var m: ScreenerModel
    var body: some View {
        let r = m.result
        let (fl, fc) = m.freshness
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 18) {
                Text("主").font(.system(size: 26, weight: .bold)).foregroundColor(Theme.yellow)
                    .frame(width: 60, height: 60)
                    .background(RoundedRectangle(cornerRadius: 14).fill(Theme.yellow.opacity(0.06)))
                    .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.yellow.opacity(0.85), lineWidth: 1.5))
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 10) {
                        Text("主力选股").font(.system(size: 24, weight: .semibold))
                        Pill(text: "A股全市场 \(grouped(r?.stocks ?? 0)) 只", color: Theme.yellow)
                    }
                    HStack(spacing: 6) {
                        Circle().fill(fc).frame(width: 7, height: 7)
                        Text(fl).font(.system(size: 13, weight: .semibold)).foregroundColor(fc)
                        Text("· 8 种K线与筹码形态，每天收盘或盘中扫描").font(.system(size: 12)).foregroundColor(Theme.dim)
                    }
                }
                Spacer()
                TimelineView(.periodic(from: .now, by: 1)) { _ in
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(beijingString("HH:mm:ss")).font(.system(size: 40, weight: .bold, design: .monospaced))
                        Text("北京时间 · \(beijingString("yyyy-MM-dd EEEE"))").font(.system(size: 11.5)).foregroundColor(Theme.dim)
                    }
                }
                Rectangle().fill(Theme.line).frame(width: 1, height: 64)
                VStack(alignment: .leading, spacing: 4) {
                    kv("数据日期", r?.data_date ?? "—", m.freshness.1)
                    kv("行情时间", r?.quote_time ?? "—", Theme.ink)
                    kv("扫描完成", r.map { String($0.generated.suffix(8)) } ?? "—", Theme.ink)
                    kv("信号", "\(r?.count ?? 0) 条（近 \(r?.days ?? 3) 日）", Theme.ink)
                }
                .frame(width: 230)
            }
            HStack(spacing: 12) {
                Button { Task { await m.run() } } label: {
                    Label(m.running ? "正在更新…" : "更新行情并扫描", systemImage: m.running ? "hourglass" : "arrow.clockwise")
                        .frame(minWidth: 130)
                }
                .buttonStyle(.borderedProminent).tint(Theme.yellow.opacity(0.85)).disabled(m.running)
                .keyboardShortcut("r")
                Toggle("A股交易时段每 10 分钟自动更新", isOn: $m.autoRefresh).toggleStyle(.checkbox)
                Text("· 每次扫描自动存入数据库").font(.system(size: 11.5)).foregroundColor(Theme.dim)
                if let reg = m.result?.regime {
                    Text(reg.above_ma20 ? "大盘（沪深300）在 20 日线上：筹码峰突破、箱体突破为回测有效组合" : "大盘（沪深300）在 20 日线下：回测显示各方法此时普遍跑输大盘，谨慎")
                        .font(.system(size: 11.5, weight: .medium)).foregroundColor(reg.above_ma20 ? Theme.green : Theme.yellow).lineLimit(1)
                }
                Spacer()
            }
            if m.running || (m.status?.exit ?? 0) != 0, let log = m.status?.log, !log.isEmpty {
                Text(log.split(separator: "\n").suffix(3).joined(separator: "\n"))
                    .font(monoF(11)).foregroundColor(Theme.dim).frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8).background(RoundedRectangle(cornerRadius: 6).fill(Theme.panel2))
            }
            if let e = m.error, m.result == nil { Text(e).foregroundColor(Theme.red).font(.system(size: 12)) }
        }
        .padding(16).panel()
    }
    func kv(_ k: String, _ v: String, _ c: Color) -> some View {
        HStack {
            Text(k).font(.system(size: 12)).foregroundColor(Theme.dim)
            Spacer()
            Text(v).font(monoF(12.5, .semibold)).foregroundColor(c).lineLimit(1)
        }
    }
}

struct ScrFilters: View {
    @EnvironmentObject var m: ScreenerModel
    var body: some View {
        HStack(spacing: 8) {
            ForEach(SCR_METHODS, id: \.self) { k in
                let on = m.methods.contains(k)
                let c = Color(hex: SCR_COLORS[k] ?? "#5B8DEF")
                let v = m.verdicts[k] ?? ""
                Button {
                    if on { m.methods.remove(k) } else { m.methods.insert(k) }
                } label: {
                    HStack(spacing: 5) {
                        Text(k).font(.system(size: 12, weight: .semibold))
                        Text("\(m.count(k))").font(monoF(11))
                        if v.hasPrefix("有效") { Text("✓").font(.system(size: 10, weight: .bold)).foregroundColor(Theme.green) }
                    }
                    .padding(.horizontal, 9).padding(.vertical, 4)
                    .foregroundColor(on ? Theme.ink : Theme.faint)
                    .background(Capsule().fill(on ? c.opacity(0.22) : Color.clear))
                    .overlay(Capsule().stroke(on ? c : Theme.line))
                }
                .buttonStyle(.plain)
                .help(v.isEmpty ? k : "回测结论：\(v)")
            }
            Button { m.showWatch.toggle() } label: {
                HStack(spacing: 5) {
                    Image(systemName: "eye").font(.system(size: 10, weight: .bold))
                    Text("假跌破观察").font(.system(size: 12, weight: .semibold))
                    Text("\(m.result?.watch?.count ?? 0)").font(monoF(11))
                }
                .padding(.horizontal, 9).padding(.vertical, 4)
                .foregroundColor(m.showWatch ? Theme.bg : Color(hex: "#F08A3C"))
                .background(Capsule().fill(m.showWatch ? Color(hex: "#F08A3C") : Color.clear))
                .overlay(Capsule().stroke(Color(hex: "#F08A3C")))
            }
            .buttonStyle(.plain)
            .help("已翻回颈线、还没突破上颈线的股票：突破上颈线那天才出买入信号")
            Spacer(minLength: 8)
            Picker("", selection: $m.days) { Text("仅最新交易日").tag(0); Text("近 3 个交易日").tag(2) }
                .labelsHidden().frame(width: 130)
            Picker("", selection: $m.minScore) { Text("全部分数").tag(0); Text("≥ 60 分").tag(60); Text("≥ 80 分").tag(80) }
                .labelsHidden().frame(width: 100)
            Toggle("只看回测验证有效", isOn: $m.validatedOnly).toggleStyle(.checkbox)
        }
        .padding(.horizontal, 14).padding(.vertical, 8).panel()
    }
}

struct WatchList: View {
    @EnvironmentObject var m: ScreenerModel
    var body: some View {
        let ws = m.result?.watch ?? []
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "假跌破观察 · \(ws.count) 只", trailing: "按离上颈线由近到远 · 收盘突破上颈线当天出买入信号")
            Text("这些股票已经“假跌破回升”（跌破前低后翻回颈线），但回测显示翻回当天买入没有优势；等收盘突破上颈线、且沪深300 在 20 日线上时再买，两年都跑赢大盘。期间收盘再跌破颈线就移出名单。")
                .font(.system(size: 11.5)).foregroundColor(Theme.dim).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 0) {
                Text("股票").frame(width: 170, alignment: .leading)
                Text("翻回日").frame(width: 70, alignment: .leading)
                Text("颈线").frame(width: 70, alignment: .trailing)
                Text("上颈线").frame(width: 70, alignment: .trailing)
                Text("现价").frame(width: 70, alignment: .trailing)
                Text("距上颈线").frame(width: 80, alignment: .trailing)
                Text("已等/剩余").frame(width: 90, alignment: .trailing)
                Text("回撤").frame(width: 60, alignment: .trailing)
                Spacer()
            }
            .font(.system(size: 11)).foregroundColor(Theme.dim)
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(ws) { w in
                        HStack(spacing: 0) {
                            HStack(spacing: 5) {
                                Text(w.name).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                                Text(w.code).font(monoF(10)).foregroundColor(Theme.dim)
                            }
                            .frame(width: 170, alignment: .leading)
                            Text(String(w.date.suffix(5))).font(monoF(12)).frame(width: 70, alignment: .leading)
                            Text(String(format: "%.2f", w.neck)).font(monoF(12)).foregroundColor(Theme.dim).frame(width: 70, alignment: .trailing)
                            Text(String(format: "%.2f", w.upper)).font(monoF(12, .semibold)).foregroundColor(Color(hex: "#F08A3C")).frame(width: 70, alignment: .trailing)
                            Text(String(format: "%.2f", w.close)).font(monoF(12)).frame(width: 70, alignment: .trailing)
                            Text(String(format: "%.1f%%", w.to_upper)).font(monoF(12, .bold))
                                .foregroundColor(w.to_upper <= 3 ? Theme.gold : Theme.ink).frame(width: 80, alignment: .trailing)
                            Text("\(w.waited) / \(w.left) 天").font(monoF(11.5)).foregroundColor(Theme.dim).frame(width: 90, alignment: .trailing)
                            Text(String(format: "%.0f%%", w.dd)).font(monoF(11.5)).foregroundColor(Theme.dim).frame(width: 60, alignment: .trailing)
                            if let pe = w.pe, pe < 0 { Text("亏损股").font(.system(size: 10.5)).foregroundColor(Theme.yellow).padding(.leading, 10) }
                            Spacer()
                        }
                        .padding(.vertical, 5).padding(.horizontal, 6)
                        .background(RoundedRectangle(cornerRadius: 5).fill(w.to_upper <= 3 ? Theme.gold.opacity(0.06) : Color.clear))
                    }
                }
            }
        }
        .padding(14).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).panel()
    }
}

struct ScrList: View {
    @EnvironmentObject var m: ScreenerModel
    var body: some View {
        if m.showWatch { WatchList() } else { ScrListBody() }
    }
}

struct ScrListBody: View {
    @EnvironmentObject var m: ScreenerModel
    var body: some View {
        let rows = m.rows
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "选股结果 · \(rows.count) 条", trailing: "✓ = 回测验证有效的方法 · 点一行看详情")
            HStack(spacing: 0) {
                Group {
                    Text("信号日").frame(width: 86, alignment: .leading)
                    Text("股票").frame(width: 150, alignment: .leading)
                    Text("方法").frame(width: 112, alignment: .leading)
                    Text("评分").frame(width: 50, alignment: .trailing)
                    Text("信号价").frame(width: 72, alignment: .trailing)
                    Text("当天涨跌").frame(width: 72, alignment: .trailing)
                    Text("至今").frame(width: 68, alignment: .trailing)
                    Text("止损").frame(width: 72, alignment: .trailing)
                }
                Text("提示").frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 14)
            }
            .font(.system(size: 11)).foregroundColor(Theme.dim)
            if rows.isEmpty {
                Spacer()
                Text(m.result == nil ? "还没有扫描结果" : "当前筛选下没有信号").foregroundColor(Theme.dim).frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing: 3) { ForEach(rows) { ScrRow(sig: $0) } }
                }
            }
        }
        .padding(14).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).panel()
    }
}

struct ScrRow: View {
    @EnvironmentObject var m: ScreenerModel
    let sig: ScrSignal
    var body: some View {
        let c = Color(hex: SCR_COLORS[sig.method] ?? "#5B8DEF")
        let sel = m.selected?.id == sig.id
        let ok = sig.validated == true
        HStack(spacing: 0) {
            Group {
                FavStar(source: "screener", market: "cn", date: sig.date, code: sig.code, name: sig.name, method: sig.method, price: sig.close, size: 12)
                    .frame(width: 22, alignment: .leading)
                Text(String(sig.date.suffix(5))).font(monoF(12)).foregroundColor(sig.days_ago == 0 ? Theme.ink : Theme.dim)
                    .frame(width: 64, alignment: .leading)
                HStack(spacing: 5) {
                    Text(sig.name).font(.system(size: 13.5, weight: .semibold)).lineLimit(1)
                    Text(sig.code).font(monoF(10)).foregroundColor(Theme.dim)
                }
                .frame(width: 150, alignment: .leading)
                HStack(spacing: 4) {
                    Text(sig.method).font(.system(size: 12, weight: .semibold)).foregroundColor(c)
                    if ok { Text("✓").font(.system(size: 10, weight: .bold)).foregroundColor(Theme.green) }
                }
                .frame(width: 112, alignment: .leading)
                Text("\(Int(sig.score))").font(monoF(13, .bold)).foregroundColor(sig.score >= 80 ? Theme.gold : Theme.ink)
                    .frame(width: 50, alignment: .trailing)
                Text(sig.close.map { String(format: "%.2f", $0) } ?? "—").font(monoF(12)).frame(width: 72, alignment: .trailing)
                Text(sig.pct.map { signed($0) } ?? "—").font(monoF(12)).foregroundColor(Theme.up(sig.pct ?? 0)).frame(width: 72, alignment: .trailing)
                Text(sig.chg_since.map { signed($0, 1) } ?? "—").font(monoF(12)).foregroundColor(Theme.up(sig.chg_since ?? 0)).frame(width: 68, alignment: .trailing)
                Text(sig.stop.map { String(format: "%.2f", $0) } ?? "—").font(monoF(12))
                    .foregroundColor(sig.below_stop == true ? Theme.red : Theme.dim).frame(width: 72, alignment: .trailing)
            }
            Text(hint).font(.system(size: 11)).foregroundColor(sig.below_stop == true ? Theme.red : Theme.dim)
                .lineLimit(1).frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 14)
        }
        .padding(.vertical, 6).padding(.horizontal, 6)
        .background(RoundedRectangle(cornerRadius: 6).fill(sel ? c.opacity(0.16) : (ok ? Theme.green.opacity(0.05) : Color.clear)))
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(sel ? c.opacity(0.7) : Color.clear))
        .contentShape(Rectangle())
        .onTapGesture { m.selectedID = sig.id }
    }
    var hint: String {
        if sig.below_stop == true { return "已跌破止损" }
        if let f = sig.flags?.first { return f }
        return sig.validation_note ?? ""
    }
}

struct ScrDetail: View {
    @EnvironmentObject var m: ScreenerModel
    @EnvironmentObject var st: Store
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle(text: "信号详情", trailing: m.selected.map { $0.date } ?? "")
            if let s = m.selected {
                let c = Color(hex: SCR_COLORS[s.method] ?? "#5B8DEF")
                HStack(spacing: 8) {
                    Text(s.name).font(.system(size: 21, weight: .bold))
                    Text(s.code).font(monoF(12)).foregroundColor(Theme.dim)
                    Pill(text: s.method, color: c, filled: true)
                    Spacer()
                    Text("\(Int(s.score)) 分").font(monoF(20, .bold)).foregroundColor(s.score >= 80 ? Theme.gold : Theme.ink)
                    FavStar(source: "screener", market: "cn", date: s.date, code: s.code, name: s.name, method: s.method, price: s.close, size: 18)
                }
                Text(s.validation_note ?? "").font(.system(size: 12, weight: .semibold))
                    .foregroundColor(s.validated == true ? Theme.green : Theme.yellow)
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        if let e = s.entry_rule { block("建仓规则", [e], Theme.ink) }
                        if let d = s.detail, !d.isEmpty { block("形态依据", d, Theme.ink.opacity(0.85)) }
                        HStack(spacing: 18) {
                            num("信号价", s.close); num("最新价", s.last_close); num("止损", s.stop)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("至今").font(.system(size: 11)).foregroundColor(Theme.dim)
                                Text(s.chg_since.map { signed($0, 1) } ?? "—").font(monoF(14, .semibold)).foregroundColor(Theme.up(s.chg_since ?? 0))
                            }
                        }
                        if let t = s.targets, !t.isEmpty {
                            block("目标位", [t.map { String(format: "%.2f", $0) }.joined(separator: " / ")], Theme.green)
                        }
                        if let f = s.flags, !f.isEmpty { block("风险提示", f, Theme.yellow) }
                        if let r = s.resonance, !r.isEmpty { block("共振", ["10 个交易日内还出现了 " + r.joined(separator: "、") + "（回测显示共振不提高胜率）"], Theme.dim) }
                        Button { st.openStock(s.code) } label: { Label("个股研判 \(s.code) →", systemImage: "chart.line.uptrend.xyaxis") }
                            .buttonStyle(.link).padding(.top, 4)
                        HStack(spacing: 18) {
                            if let pe = s.pe { Text("市盈率 \(String(format: "%.1f", pe))").font(.system(size: 11.5)).foregroundColor(Theme.dim) }
                            if let to = s.turnover { Text("换手 \(String(format: "%.2f", to))%").font(.system(size: 11.5)).foregroundColor(Theme.dim) }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Spacer()
                Text("选一条信号查看详情").foregroundColor(Theme.dim).frame(maxWidth: .infinity)
                Spacer()
            }
        }
        .padding(14).frame(maxHeight: .infinity, alignment: .topLeading).panel()
    }
    func block(_ t: String, _ lines: [String], _ c: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(t).font(.system(size: 11, weight: .semibold)).foregroundColor(Theme.dim)
            ForEach(lines, id: \.self) { Text("· " + $0).font(.system(size: 12.5)).foregroundColor(c).fixedSize(horizontal: false, vertical: true) }
        }
    }
    func num(_ t: String, _ v: Double?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(t).font(.system(size: 11)).foregroundColor(Theme.dim)
            Text(v.map { String(format: "%.2f", $0) } ?? "—").font(monoF(14, .semibold))
        }
    }
}

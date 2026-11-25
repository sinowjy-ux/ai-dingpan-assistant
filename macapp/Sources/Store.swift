import Foundation
import SwiftUI

enum Mode: String { case replay, live }

struct LogLine: Identifiable {
    enum Kind { case info, start, done, signal, cut, warn }
    let id = UUID()
    let time: String
    let text: String
    let kind: Kind
    var color: Color? = nil
}

enum StratStatus { case idle, scanning, done }

struct Window: Hashable, Identifiable {
    let start: Int, end: Int, label: String
    var id: String { label }
}

func windowsFor(_ market: String) -> [Window] {
    if market == "us" {
        return [Window(start: 1000, end: 1200, label: "10:00–12:00 两小时"),
                Window(start: 930, end: 1600, label: "09:30–16:00 全天"),
                Window(start: 930, end: 1200, label: "09:30–12:00 上午"),
                Window(start: 1300, end: 1600, label: "13:00–16:00 下午")]
    }
    return [Window(start: 1000, end: 1330, label: "10:00–13:30 两小时"),
            Window(start: 930, end: 1500, label: "09:30–15:00 全天"),
            Window(start: 930, end: 1130, label: "09:30–11:30 上午"),
            Window(start: 1300, end: 1500, label: "13:00–15:00 下午")]
}

let SIZES: [(Int, String)] = [(1500, "前 1500 只"), (3000, "前 3000 只"), (0, "全市场")]
let SPEEDS: [(String, Double)] = [("慢 0.6秒/分", 0.6), ("中 0.25秒/分", 0.25), ("快 0.08秒/分", 0.08)]

@MainActor
final class Store: ObservableObject {
    // 启动
    @Published var booting = true
    @Published var bootError: String?
    @Published var meta: Meta?

    // 控制
    @Published var page: Page = .dashboard
    @Published var appearance: String = Appearance.current
    @Published var stockCode: String?            // 个股研判：从主力选股跳过来时带上的代码
    var stockURL: URL {
        var u = Backend.shared.base.absoluteString + "/?embed=1&theme=" + appearance
        if let c = stockCode { u += "&code=" + c + "&market=" + ("A股".addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "") }
        return URL(string: u)!
    }
    func openStock(_ code: String) { stockCode = code; page = .stock }
    func setAppearance(_ v: String) {
        appearance = v
        UserDefaults.standard.set(v, forKey: "appearance")
        Appearance.apply(v)
    }
    @Published var showDisclaimer = !UserDefaults.standard.bool(forKey: "disclaimer_v1") && !CommandLine.arguments.contains("--snapshot") && !CommandLine.arguments.contains("--record")
    @Published var market = "cn"
    @Published var n = 1500
    @Published var mode: Mode = .replay
    @Published var date: String = ""
    @Published var window: Window = windowsFor("cn")[0]
    @Published var speedIdx = 1

    // 回放
    @Published var replay: Replay?
    @Published var clockIdx = 0
    @Published var playing = false
    @Published var finished = false
    @Published var loading = false
    private var startIdx = 0, endIdx = 0
    private var byMinute: [Int: [Signal]] = [:]
    private var playTask: Task<Void, Never>?
    private var skipping = false

    // 共用
    @Published var shown: [Signal] = []
    @Published var logs: [LogLine] = []
    @Published var selectedID: String?
    @Published var series: [String: Series] = [:]
    @Published var errorText: String?
    @Published var toast: Signal?          // 最新命中（未剔除）的醒目提示
    @Published var newHitIDs: Set<String> = []   // 刚出现的命中，闪烁几秒

    // 实时
    @Published var live: LiveState?
    private var liveSince = 0
    private var liveTask: Task<Void, Never>?
    private var seenServerLog = Set<String>()
    private var metaTask: Task<Void, Never>?

    let api = Backend.shared

    // ---------------- 启动 ----------------
    func boot() async {
        do {
            try await api.start()
            try await reloadMeta()
            booting = false
        } catch {
            bootError = error.localizedDescription
        }
    }

    var q: String { "market=\(market)&n=\(n)" }

    func reloadMeta() async throws {
        let m = try await api.get("/api/monitor/meta?\(q)", Meta.self)
        meta = m
        if date.isEmpty || !m.dates.contains(date) { date = m.dates.last ?? "" }
        if dataset?.building == true { watchBuild() }
    }

    // ---------------- 市场 / 只数 ----------------
    var minfo: MarketInfo? { meta?.markets?[market] }
    /// 信号所属交易日（回放 = 回放日期；实盘 = 交易所当地日期），收藏/保存用
    var sigDate: String { mode == .live ? (live?.local_date ?? date) : (replay?.date ?? date) }
    var marketName: String { minfo?.name ?? (market == "us" ? "美股" : "A股") }
    var indexName: String { minfo?.index_name ?? "沪深300" }
    var sizeLabel: String { SIZES.first { $0.0 == n }?.1 ?? "\(n)" }
    var minutes: [Int] { minfo?.minutes ?? defaultMinutes(market) }
    var windows: [Window] { windowsFor(market) }
    func mIdx(_ t: Int) -> Int { indexIn(minutes, t) }
    var dataset: Dataset? { meta?.datasets?.first { $0.market == market && $0.n == n } }
    var datasetReady: Bool { dataset?.ready ?? !(meta?.dates.isEmpty ?? true) }

    func setMarket(_ m: String) {
        guard m != market else { return }
        market = m; window = windowsFor(m)[0]; date = ""
        switchDataset()
    }
    func setSize(_ v: Int) {
        guard v != n else { return }
        n = v; date = ""
        switchDataset()
    }
    private func switchDataset() {
        let wasLive = mode == .live
        stopAll()
        replay = nil; finished = false; clockIdx = 0; shown = []; logs = []; selectedID = nil; series = [:]; toast = nil
        live = nil
        Task {
            try? await reloadMeta()
            if wasLive { enterLive() }
        }
    }

    var order: [String] { minfo?.order ?? meta?.order ?? [] }
    func card(_ k: String) -> Card? { minfo?.cards[k] ?? meta?.cards[k] }
    func name(_ k: String) -> String { meta?.strategies[k] ?? k }
    func color(_ k: String) -> Color { Color(hex: card(k)?.color ?? "#5B8DEF") }

    // ---------------- 时钟与统计 ----------------
    var clockT: Int {
        if mode == .live, let s = live?.local_time ?? live?.cn_time {
            let p = s.split(separator: ":"); if p.count >= 2 { return (Int(p[0]) ?? 0) * 100 + (Int(p[1]) ?? 0) }
        }
        let m = minutes
        return m.isEmpty ? 930 : m[min(max(clockIdx, 0), m.count - 1)]
    }
    var totalMinutes: Int { market == "us" ? 390 : 240 }
    var stockCount: Int { mode == .live ? (live?.count ?? 0) : (replay?.count ?? meta?.stocks ?? 0) }
    var minutesDone: Int {
        if mode == .live {
            guard live?.status == "running" || live?.status == "lunch" || live?.status == "done" else { return 0 }
            return min(totalMinutes, mIdx(clockT) + 1)
        }
        return replay == nil ? 0 : clockIdx + 1
    }
    var scanned: Int { stockCount * minutesDone }
    var passed: [Signal] { shown.filter { $0.grade != "C" } }
    var cut: Int { shown.filter { $0.grade == "C" }.count }
    var resonance: [String] {
        var m: [String: Set<String>] = [:]
        for s in passed { m[s.code, default: []].insert(s.strategy) }
        return m.filter { $0.value.count >= 2 }.map { $0.key }
    }
    func isResonance(_ code: String) -> Bool { resonance.contains(code) }
    func signals(of k: String) -> [Signal] { shown.filter { $0.strategy == k } }

    func status(_ k: String) -> StratStatus {
        guard let w = card(k)?.window, w.count == 2 else { return .idle }
        if mode == .replay && replay == nil { return .idle }
        if mode == .live && !["running", "lunch", "done", "loading"].contains(live?.status ?? "") { return .idle }
        let t = clockT
        if t < w[0] { return .idle }
        if t > w[1] || (mode == .replay && finished) || live?.status == "done" { return .done }
        return .scanning
    }
    func progress(_ k: String) -> Double {
        guard let w = card(k)?.window, w.count == 2 else { return 0 }
        let a = mIdx(w[0]), b = mIdx(w[1]), c = mIdx(clockT)
        if status(k) == .idle { return 0 }
        return min(1, max(0, Double(c - a + 1) / Double(b - a + 1)))
    }
    var activeKey: String? {
        if let s = shown.last, clockT - s.t <= 5 { return s.strategy }
        return order.first { status($0) == .scanning }
    }
    var selected: Signal? {
        if let id = selectedID, let s = shown.first(where: { $0.id == id }) { return s }
        return passed.last ?? shown.last
    }
    var indexNow: Double? {
        if mode == .live { return live?.index_price }
        guard let r = replay else { return nil }
        return r.index.last(where: { Int($0[0]) <= clockT })?[1]
    }
    var indexPrev: Double? { mode == .live ? live?.index_prev : replay?.index_prev }

    // ---------------- 命中提示 ----------------
    private func announce(_ fresh: [Signal]) {
        let hits = fresh.filter { $0.grade != "C" }
        guard !hits.isEmpty, !skipping else { return }
        let best = hits.max { $0.score < $1.score }!
        toast = best
        let ids = Set(hits.map { $0.id })
        newHitIDs.formUnion(ids)
        let tid = best.id
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            guard let self else { return }
            if self.toast?.id == tid { withAnimation(.easeOut(duration: 0.3)) { self.toast = nil } }
            self.newHitIDs.subtract(ids)
        }
    }

    // ---------------- 回放 ----------------
    func startReplay() async {
        stopAll()
        loading = true; errorText = nil
        defer { loading = false }
        do {
            let r = try await api.get("/api/monitor/replay?\(q)&date=\(date)&start=\(window.start)&end=\(window.end)", Replay.self, timeout: 300)
            replay = r
            byMinute = Dictionary(grouping: r.signals, by: { $0.t })
            startIdx = mIdx(window.start); endIdx = mIdx(window.end)
            clockIdx = startIdx; shown = []; logs = []; selectedID = nil; finished = false; series = [:]; toast = nil
            log(fmtT(window.start), "启动 6 套策略 · \(marketName) \(r.count) 只 · 回放 \(r.date)", .info)
            for k in order { if let w = card(k)?.window, w[0] < window.start, w[1] >= window.start { log(fmtT(window.start), "启动 \(name(k))", .start, color(k)) } }
            play()
        } catch { errorText = error.localizedDescription }
    }

    func play() {
        guard replay != nil, !finished else { return }
        playing = true
        playTask?.cancel()
        playTask = Task { [weak self] in
            while let self, self.playing, !Task.isCancelled {
                self.step()
                if self.finished { break }
                try? await Task.sleep(nanoseconds: UInt64(SPEEDS[self.speedIdx].1 * 1e9))
            }
        }
    }
    func pause() { playing = false; playTask?.cancel() }
    func toggle() {
        if replay == nil || finished { Task { await startReplay() } } else if playing { pause() } else { play() }
    }
    func skipToEnd() {
        pause(); skipping = true
        while !finished && replay != nil { step() }
        skipping = false
    }
    func jump(to t: Int) {
        pause(); skipping = true
        while !finished && replay != nil && clockT < t { step() }
        skipping = false
    }

    private func step() {
        guard replay != nil else { return }
        let t = minutes[clockIdx]
        let tt = fmtT(t)
        for k in order {
            guard let w = card(k)?.window else { continue }
            if w[0] == t && t > window.start { log(tt, "启动 \(name(k))", .start, color(k)) }
        }
        if market == "cn" && t == 1300 && window.start < 1300 { log(tt, "下午开盘 · 继续扫描", .info) }
        let fresh = byMinute[t] ?? []
        for s in fresh { logSignal(s) }
        shown += fresh
        announce(fresh)
        for k in order {
            guard let w = card(k)?.window else { continue }
            if w[1] == t && t < window.end {
                let c = signals(of: k).filter { $0.grade != "C" }.count
                log(tt, "完工 \(name(k)) → 命中 \(c) 条", .done, color(k))
            }
        }
        if market == "cn" && t == 1130 && window.end > 1130 { log(tt, "午间休市", .info) }
        if clockIdx >= endIdx {
            finished = true; playing = false
            log(tt, "收工 · 命中 \(passed.count) 条（可执行 \(shown.filter { $0.grade == "A" }.count) · 观察 \(shown.filter { $0.grade == "B" }.count)）· 剔除 \(cut)", .done, Theme.green)
            return
        }
        clockIdx += 1
    }

    private func logSignal(_ s: Signal) {
        if s.grade == "C" { log(s.time, "剔除 \(s.name) \(s.strategy_name) 纪律分 \(s.score)", .cut) }
        else { log(s.time, "★ 命中 \(s.name) \(s.strategy_name) 纪律分 \(s.score)\(s.grade)", .signal, Theme.grade(s.grade)) }
    }

    private func log(_ t: String, _ s: String, _ k: LogLine.Kind, _ c: Color? = nil) {
        logs.append(LogLine(time: t, text: s, kind: k, color: c))
        if logs.count > 400 { logs.removeFirst(logs.count - 400) }
    }

    // ---------------- 实时 ----------------
    func enterLive() {
        stopAll()
        mode = .live; shown = []; logs = []; selectedID = nil; liveSince = 0; seenServerLog = []; series = [:]; toast = nil
        liveTask = Task { [weak self] in
            while let self, !Task.isCancelled, self.mode == .live {
                await self.pollLive()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }
    func enterReplay() {
        stopAll()
        mode = .replay; shown = []; logs = []; selectedID = nil; replay = nil; finished = false; clockIdx = 0; toast = nil
    }
    func startLive() async {
        _ = try? await api.get("/api/monitor/live/start?\(q)", LiveState.self)
        shown = []; liveSince = 0; logs = []; seenServerLog = []
        await pollLive()
    }
    func stopLive() async {
        _ = try? await api.get("/api/monitor/live/stop?\(q)", LiveState.self)
        await pollLive()
    }
    func setNotify(_ on: Bool) async {
        struct R: Codable { let notify: Bool }
        _ = try? await api.get("/api/monitor/live/notify?\(q)&on=\(on ? 1 : 0)", R.self)
        await pollLive()
    }
    func pollLive() async {
        let m = market
        guard let st = try? await api.get("/api/monitor/live?\(q)&since=\(liveSince)", LiveState.self), m == market else { return }
        if let lm = st.market, lm != market { return }
        live = st
        liveSince += st.signals.count
        for line in st.log where !seenServerLog.contains(line) {
            seenServerLog.insert(line)
            log(String(line.prefix(5)), String(line.dropFirst(9)), .info)
        }
        for s in st.signals { logSignal(s) }
        shown += st.signals
        announce(st.signals.filter { $0.backfill != true })
    }
    var liveActive: Bool { ["waiting", "loading", "running", "lunch"].contains(live?.status ?? "") }

    func stopAll() { pause(); liveTask?.cancel(); liveTask = nil }

    // ---------------- 数据下载 ----------------
    func download() async {
        struct R: Codable { let started: Bool }
        _ = try? await api.get("/api/monitor/refresh?\(q)", R.self)
        try? await reloadMeta()
        watchBuild()
    }
    private func watchBuild() {
        guard metaTask == nil else { return }
        metaTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                try? await self.reloadMeta()
                if self.dataset?.building != true { break }
            }
            self?.metaTask = nil
        }
    }

    // ---------------- 分时 ----------------
    func loadSeries(for s: Signal) async {
        let key = seriesKey(s)
        if series[key] != nil && mode == .replay { return }
        let path = mode == .live ? "/api/monitor/series?\(q)&live=1&code=\(s.code)" : "/api/monitor/series?\(q)&date=\(replay?.date ?? date)&code=\(s.code)"
        if let r = try? await api.get(path, Series.self) { series[key] = r }
    }
    private func seriesKey(_ s: Signal) -> String { market + (mode == .live ? "live" : (replay?.date ?? date)) + s.code }
    func seriesFor(_ s: Signal) -> Series? { series[seriesKey(s)] }
}

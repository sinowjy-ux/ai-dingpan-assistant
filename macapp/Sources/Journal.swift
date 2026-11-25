import SwiftUI

// MARK: - 通用 JSON（复盘/数据库接口字段多且可选，用动态 JSON 读取）

enum JV: Decodable, Hashable {
    case o([String: JV]), a([JV]), s(String), n(Double), b(Bool), null

    init(from d: Decoder) throws {
        let c = try d.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let x = try? c.decode(Bool.self) { self = .b(x) }
        else if let x = try? c.decode(Double.self) { self = .n(x) }
        else if let x = try? c.decode(String.self) { self = .s(x) }
        else if let x = try? c.decode([JV].self) { self = .a(x) }
        else if let x = try? c.decode([String: JV].self) { self = .o(x) }
        else { self = .null }
    }
    subscript(_ k: String) -> JV { if case .o(let m) = self { return m[k] ?? .null }; return .null }
    subscript(_ i: Int) -> JV { if case .a(let a) = self, i < a.count { return a[i] }; return .null }
    var arr: [JV] { if case .a(let a) = self { return a }; return [] }
    var str: String {
        switch self {
        case .s(let x): return x
        case .n(let x): return x == x.rounded() && abs(x) < 1e12 ? String(Int(x)) : String(x)
        case .b(let x): return x ? "true" : "false"
        default: return ""
        }
    }
    var num: Double? {
        switch self {
        case .n(let x): return x
        case .s(let x): return Double(x)
        case .b(let x): return x ? 1 : 0
        default: return nil
        }
    }
    var int: Int { Int(num ?? 0) }
    var bool: Bool { if case .b(let x) = self { return x }; return (num ?? 0) != 0 }
    var isNull: Bool { if case .null = self { return true }; return false }
    var keys: [String] { if case .o(let m) = self { return Array(m.keys) }; return [] }
}

extension Backend {
    func post(_ path: String, _ body: [String: Any], timeout: TimeInterval = 120) async throws -> JV {
        var req = URLRequest(url: URL(string: base.absoluteString + path)!)
        req.httpMethod = "POST"
        req.timeoutInterval = timeout
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, resp) = try await URLSession.shared.data(for: req)
        if let h = resp as? HTTPURLResponse, h.statusCode != 200 {
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw NSError(domain: "AIDP", code: h.statusCode, userInfo: [NSLocalizedDescriptionKey: msg ?? "HTTP \(h.statusCode)"])
        }
        return try JSONDecoder().decode(JV.self, from: data)
    }
}

func pctText(_ v: JV, _ digits: Int = 2) -> String { v.num.map { signed($0, digits) } ?? "—" }
func yi(_ x: Double?) -> String {
    guard let x else { return "—" }
    return abs(x) >= 10000 ? String(format: "%.2f 万亿", x / 10000) : String(format: "%.1f 亿", x)
}
func favKey(_ source: String, _ market: String, _ date: String, _ code: String, _ method: String) -> String {
    [source, market, date, code, method].joined(separator: "|")
}

// MARK: - 数据库模型（统计页、复盘页、收藏）

enum DelUnit: String, CaseIterable, Identifiable {
    case day, week, month, year, before
    var id: String { rawValue }
    var label: String { ["day": "按天", "week": "按周", "month": "按月", "year": "按年", "before": "某天之前全部"][rawValue]! }
}

@MainActor
final class JournalModel: ObservableObject {
    @Published var summary: JV = .null
    @Published var day: JV = .null
    @Published var date: String = ""
    @Published var review: JV = .null           // 当前查看的复盘（完整）
    @Published var reviewDate: String = ""
    @Published var reviewRunning = false
    @Published var reviewLog: [String] = []
    @Published var error: String?
    @Published var favKeys: Set<String> = []
    @Published var sourceFilter = "all"          // all | screener | monitor
    @Published var toast: String?
    @Published var scrollTo: Int?               // 自检用：复盘页滚动到第几节
    // 删除
    @Published var delUnit: DelUnit = .month
    @Published var delValue: String = ""
    @Published var delWhat: Set<String> = ["picks", "reviews", "favorites", "analyses"]
    @Published var delPreview: JV = .null
    @Published var confirmDelete = false
    let api = Backend.shared

    var dates: [JV] { summary["dates"].arr }
    var reviewDates: [String] { dates.filter { !$0["review"].isNull && $0["review"].str != "false" && $0["review"].str != "" }.map { $0["date"].str } }

    func load() async {
        do {
            summary = try await api.get("/api/db/summary", JV.self)
            favKeys = Set(summary["favorites"].arr.map { favKey($0["source"].str, $0["market"].str, $0["date"].str, $0["code"].str, $0["method"].str) })
            if date.isEmpty || !dates.contains(where: { $0["date"].str == date }) { date = dates.first?["date"].str ?? beijingString("yyyy-MM-dd") }
            await loadDay()
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    func loadDay() async {
        guard !date.isEmpty else { return }
        day = (try? await api.get("/api/db/day?date=\(date)", JV.self)) ?? .null
    }

    func select(_ d: String) { date = d; Task { await loadDay() } }

    func flash(_ t: String) {
        toast = t
        Task { try? await Task.sleep(nanoseconds: 2_500_000_000); if toast == t { toast = nil } }
    }

    // 收藏
    func isFav(_ k: String) -> Bool { favKeys.contains(k) }
    func toggleFav(source: String, market: String, date: String, code: String, name: String, method: String, price: Double?, note: String = "") async {
        let k = favKey(source, market, date, code, method)
        let on = !favKeys.contains(k)
        var item: [String: Any] = ["source": source, "market": market, "date": date, "code": code, "name": name, "method": method, "note": note]
        if let price { item["price"] = price }
        do {
            _ = try await api.post("/api/db/favorite", ["item": item, "on": on ? 1 : 0])
            if on { favKeys.insert(k) } else { favKeys.remove(k) }
            flash(on ? "★ 已收藏 \(name)" : "已取消收藏 \(name)")
            await load()
        } catch { flash("收藏失败：\(error.localizedDescription)") }
    }

    // 保存
    func saveScreener() async {
        do {
            let r = try await api.post("/api/db/save_screener", [:])
            flash("主力选股已存入数据库：\(r["saved"].int) 条")
            await load()
        } catch { flash("保存失败：\(error.localizedDescription)") }
    }
    func saveMonitor(date: String, market: String, n: Int) async {
        do {
            let r = try await api.post("/api/db/save_monitor", ["date": date, "market": market, "n": n], timeout: 300)
            flash("盯盘 \(date) 已存入数据库：信号 \(r["saved"].int) 条，其中命中 \(r["hits"].int) 条")
            await load()
        } catch { flash("保存失败：\(error.localizedDescription)") }
    }
    func evaluate() async {
        _ = try? await api.post("/api/db/evaluate", [:], timeout: 300)
        flash("比对已更新")
        await load()
    }

    // 复盘
    func loadReview(_ d: String? = nil) async {
        let path = d.map { "/api/review?date=\($0)" } ?? "/api/review"
        if let r = try? await api.get(path, JV.self) { review = r; reviewDate = r["date"].str } else if d == nil { review = .null }
        if let st = try? await api.get("/api/review/status", JV.self), st["running"].bool, !reviewRunning { await waitReview() }
    }
    func buildReview() async {
        _ = try? await api.post("/api/review/build", [:])
        await waitReview()
    }
    private func waitReview() async {
        reviewRunning = true
        while true {
            guard let st = try? await api.get("/api/review/status", JV.self) else { break }
            reviewLog = st["log"].arr.map { $0.str }
            if !st["running"].bool { break }
            try? await Task.sleep(nanoseconds: 1_500_000_000)
        }
        reviewRunning = false
        await loadReview()
        await load()
    }

    // 删除
    func defaultDelValue() -> String {
        let t = beijingString("yyyy-MM-dd")
        switch delUnit {
        case .day, .week: return date.isEmpty ? t : date
        case .month: return String((date.isEmpty ? t : date).prefix(7))
        case .year: return String((date.isEmpty ? t : date).prefix(4))
        case .before:
            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "Asia/Shanghai")
            return f.string(from: Date().addingTimeInterval(-30 * 86400))
        }
    }
    var delQuery: String {
        let w = ["picks", "reviews", "favorites", "analyses"].filter { delWhat.contains($0) }.joined(separator: ",")
        return "unit=\(delUnit.rawValue)&value=\(delValue)&what=\(w)"
    }
    func previewDelete() async {
        delPreview = (try? await api.get("/api/db/delete_preview?\(delQuery)", JV.self)) ?? .null
    }
    func doDelete() async {
        let w = ["picks", "reviews", "favorites", "analyses"].filter { delWhat.contains($0) }.joined(separator: ",")
        do {
            let r = try await api.post("/api/db/delete", ["unit": delUnit.rawValue, "value": delValue, "what": w])
            let d = r["deleted"]
            flash("已删除 \(r["from"].str) ~ \(r["to"].str)：选股/信号 \(d["picks"].int) 条，复盘 \(d["reviews"].int) 篇，收藏 \(d["favorites"].int) 条")
            delPreview = .null
            await load()
        } catch { flash("删除失败：\(error.localizedDescription)") }
    }
}

// MARK: - 收藏星标按钮

struct FavStar: View {
    @EnvironmentObject var j: JournalModel
    let source: String, market: String, date: String, code: String, name: String, method: String
    var price: Double? = nil
    var size: CGFloat = 15
    var body: some View {
        let on = j.isFav(favKey(source, market, date, code, method))
        Button {
            Task { await j.toggleFav(source: source, market: market, date: date, code: code, name: name, method: method, price: price) }
        } label: {
            Image(systemName: on ? "star.fill" : "star").font(.system(size: size, weight: .semibold))
                .foregroundColor(on ? Theme.gold : Theme.faint)
        }
        .buttonStyle(.plain)
        .help(on ? "取消收藏" : "收藏（存进数据库，统计页可查）")
    }
}

struct JournalToast: View {
    let text: String
    var body: some View {
        Text(text).font(.system(size: 13, weight: .semibold)).foregroundColor(Theme.ink)
            .padding(.horizontal, 16).padding(.vertical, 9)
            .background(Capsule().fill(Theme.panel2))
            .overlay(Capsule().stroke(Theme.gold.opacity(0.8), lineWidth: 1))
            .fxShadow(color: .black.opacity(0.4), radius: 10)
    }
}

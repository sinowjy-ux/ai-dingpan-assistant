import AppKit
import Foundation
import SwiftUI

// 与 Python 接口 /api/monitor/* 对应的数据结构

struct Card: Codable {
    let char: String
    let en: String
    let tag: String
    let rule: String
    let window: [Int]
    let color: String
}

struct MarketInfo: Codable {
    let name: String
    let index_name: String
    let minutes: [Int]
    let order: [String]
    let cards: [String: Card]
    let time_ok: [Int]
    let currency: String
    let phase: String
    let local_time: String
}

struct Dataset: Codable, Identifiable {
    let market: String
    let n: Int
    let label: String
    let ready: Bool
    let dates: [String]
    let built: String?
    let stocks: Int
    let building: Bool
    let log: [String]
    let est_min: Int
    var id: String { market + String(n) }
}

struct Meta: Codable {
    let market: String?
    let n: Int?
    let markets: [String: MarketInfo]?
    let datasets: [Dataset]?
    let dates: [String]
    let built: String?
    let stocks: Int
    let building: Bool
    let build_log: [String]
    let strategies: [String: String]
    let desc: [String: String]
    let cards: [String: Card]
    let order: [String]
    let phase: String
    let cn_time: String
}

struct Check: Codable, Hashable {
    let name: String
    let pts: Int
    let ok: Bool
    let note: String
}

struct After: Codable, Hashable {
    let close: Double
    let max_up: Double
    let max_dn: Double
    let stopped: Bool
}

struct Signal: Codable, Identifiable, Hashable {
    let time: String
    let t: Int
    let code: String
    let name: String
    let strategy: String
    let strategy_name: String
    let price: Double
    let chg: Double
    let lb: Double
    let vwap: Double
    let stop: Double
    let risk: Double
    let reason: String
    let score: Int
    let grade: String
    let verdict: String
    let checks: [Check]
    let after: After?
    let backfill: Bool?
    let market: String?
    var id: String { code + strategy + String(t) }
}

struct Replay: Codable {
    let date: String
    let start: Int
    let end: Int
    let count: Int
    let signals: [Signal]
    let index: [[Double]]
    let index_prev: Double?
    let minutes: [Int]?
}

struct LiveState: Codable {
    let market: String?
    let n: Int?
    let local_time: String?
    let local_date: String?
    let status: String
    let date: String?
    let count: Int
    let polls: Int
    let last_poll: String?
    let log: [String]
    let total: Int
    let signals: [Signal]
    let notify: Bool
    let phase: String
    let index_price: Double?
    let index_prev: Double?
    let cn_time: String
}

struct Series: Codable {
    let code: String
    let name: String
    let pc: Double?
    let t: [Int]
    let p: [Double]
    let v: [Double]
}

// 交易分钟：09:30–11:30，13:00–15:00，共 241 个
// 交易分钟（默认值），实际按市场从后台 meta 取
func defaultMinutes(_ market: String) -> [Int] {
    var a: [Int] = []
    let sess = market == "us" ? [(930, 1600)] : [(930, 1130), (1300, 1500)]
    for (x, y) in sess { var t = x; while t <= y { a.append(t); t += (t % 100 == 59) ? 41 : 1 } }
    return a
}
func indexIn(_ mins: [Int], _ t: Int) -> Int { mins.firstIndex(where: { $0 >= t }) ?? max(mins.count - 1, 0) }

func fmtT(_ t: Int) -> String { String(format: "%02d:%02d", t / 100, t % 100) }

extension Color {
    init(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        let v = UInt64(s, radix: 16) ?? 0
        self.init(red: Double((v >> 16) & 0xFF) / 255, green: Double((v >> 8) & 0xFF) / 255, blue: Double(v & 0xFF) / 255)
    }
}

extension Color {
    /// 自适应颜色：深色外观用 dark，浅色外观用 light（与网页版 theme.css 同一组色值）
    static func dyn(_ dark: String, _ light: String) -> Color {
        let d = NSColor(Color(hex: dark)), l = NSColor(Color(hex: light))
        return Color(nsColor: NSColor(name: nil) { ap in ap.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? d : l })
    }
}

/// 界面颜色：dark 深色 / light 浅色 / system 跟随系统。录制演示与截图自检时固定深色。
enum Appearance {
    static var current: String {
        let a = CommandLine.arguments
        if let i = a.firstIndex(of: "--appearance"), i + 1 < a.count { return a[i + 1] }
        if a.contains("--record") || a.contains("--snapshot") { return "dark" }
        return UserDefaults.standard.string(forKey: "appearance") ?? "dark"
    }
    @MainActor static func apply(_ v: String) {
        NSApp.appearance = v == "dark" ? NSAppearance(named: .darkAqua) : (v == "light" ? NSAppearance(named: .aqua) : nil)
    }
}

enum Theme {
    static let bg = Color.dyn("#090D12", "#F3F5F8")
    static let panel = Color.dyn("#0F151C", "#FFFFFF")
    static let panel2 = Color.dyn("#141B24", "#F1F4F8")
    static let line = Color.dyn("#1E2834", "#DDE3EA")
    static let ink = Color.dyn("#E6EDF3", "#122033")
    static let dim = Color.dyn("#7A8796", "#5A6A80")
    static let faint = Color.dyn("#4A5563", "#94A3B8")
    static let green = Color.dyn("#3CC48A", "#16875A")
    static let red = Color.dyn("#F0605A", "#D23F31")
    static let yellow = Color.dyn("#E8B931", "#B7791F")
    static let blue = Color.dyn("#5B8DEF", "#2563EB")
    static let gold = Color.dyn("#F5C451", "#B8860B")
    static let hi = Color.dyn("#FFFFFF", "#0F172A")          // 大数字渐变的高光色
    static let cardA = Color.dyn("#121A26", "#FFFFFF")
    static let cardB = Color.dyn("#0C121B", "#F6F8FB")
    static let grid = Color.dyn("#1C2430", "#E5E9EF")       // 图表网格线

    static func grade(_ g: String) -> Color { g == "A" ? green : (g == "B" ? yellow : red) }
    static func up(_ x: Double) -> Color { x > 0 ? red : (x < 0 ? green : dim) }   // A股：红涨绿跌
}

func signed(_ x: Double, _ digits: Int = 2) -> String { (x > 0 ? "+" : "") + String(format: "%.\(digits)f", x) + "%" }
func grouped(_ n: Int) -> String {
    let f = NumberFormatter(); f.numberStyle = .decimal; f.locale = Locale(identifier: "en_US")
    return f.string(from: NSNumber(value: n)) ?? "\(n)"
}

import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillTerminate(_ notification: Notification) { Backend.shared.stop() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct AIDingPanApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var store = Store()
    @StateObject private var screener = ScreenerModel()
    @StateObject private var journal = JournalModel()

    var body: some Scene {
        WindowGroup("AI 盯盘助手") {
            RootView()
                .environmentObject(store)
                .environmentObject(screener)
                .environmentObject(journal)
                .frame(minWidth: 1360, minHeight: 820)
                .task {
                    await store.boot()
                    await SelfCheck.runIfRequested(store, journal)
                    await Recorder.runIfRequested(store, journal, screener)
                }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1600, height: 1000)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandMenu("盯盘") {
                Button("开始 / 暂停回放") { store.toggle() }.keyboardShortcut("p")
                Button("跳到结尾") { store.skipToEnd() }.keyboardShortcut("e")
                Divider()
                Button("回放复盘") { store.enterReplay() }.keyboardShortcut("1")
                Button("实时盯盘") { store.enterLive() }.keyboardShortcut("2")
                Divider()
                Button("统计页") { store.page = .dashboard }.keyboardShortcut("1", modifiers: [.command, .option])
                Button("每日复盘") { store.page = .review }.keyboardShortcut("2", modifiers: [.command, .option])
                Button("AI 盯盘页") { store.page = .monitor }.keyboardShortcut("3", modifiers: [.command, .option])
                Button("主力选股页") { store.page = .screener }.keyboardShortcut("4", modifiers: [.command, .option])
                Button("个股研判页") { store.page = .stock }.keyboardShortcut("5", modifiers: [.command, .option])
            }
        }
    }
}

/// 自检：AIDingPan --snapshot out.png [--date D] [--at 1215] [--live]
/// 启动后自动回放到指定分钟，把窗口画面存成 PNG 后退出。用于构建后验证界面。
enum SelfCheck {
    @MainActor
    static func runIfRequested(_ s: Store, _ j: JournalModel) async {
        let a = CommandLine.arguments
        guard let i = a.firstIndex(of: "--snapshot"), i + 1 < a.count else { return }
        let out = a[i + 1]
        func arg(_ k: String) -> String? { a.firstIndex(of: k).flatMap { $0 + 1 < a.count ? a[$0 + 1] : nil } }
        if s.bootError != nil { print("SELFCHECK boot error: \(s.bootError!)"); exit(2) }
        if let mk = arg("--market") { s.setMarket(mk); try? await Task.sleep(nanoseconds: 800_000_000) }
        if let nn = arg("--n").flatMap(Int.init) { s.setSize(nn); try? await Task.sleep(nanoseconds: 800_000_000) }
        if let pg = arg("--page") {
            s.page = ["review": .review, "stock": .stock][pg] ?? .dashboard
            if let c = arg("--code") { s.stockCode = c }
            if pg == "stock" { try? await Task.sleep(nanoseconds: 15_000_000_000) }
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            if let d = arg("--date") { j.select(d); try? await Task.sleep(nanoseconds: 1_500_000_000) }
            if let st = arg("--scroll").flatMap(Int.init) { j.scrollTo = st; try? await Task.sleep(nanoseconds: 1_000_000_000) }
        } else if a.contains("--screener") {
            s.page = .screener
            try? await Task.sleep(nanoseconds: 3_000_000_000)
        } else if a.contains("--live") {
            s.enterLive()
            try? await Task.sleep(nanoseconds: 2_500_000_000)
        } else {
            s.page = .monitor
            if let d = arg("--date") { s.date = d }
            await s.startReplay()
            if a.contains("--toast") { s.play(); try? await Task.sleep(nanoseconds: 6_000_000_000); s.pause() }
            if let t = arg("--at").flatMap(Int.init) { s.jump(to: t) } else { s.skipToEnd() }
            if let sig = s.shown.last(where: { $0.grade != "C" }) { s.selectedID = sig.id; await s.loadSeries(for: sig) }
        }
        try? await Task.sleep(nanoseconds: 1_500_000_000)
        guard let win = NSApp.windows.first(where: { $0.isVisible }), let view = win.contentView else { print("SELFCHECK no window"); exit(3) }
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { exit(4) }
        view.cacheDisplay(in: view.bounds, to: rep)
        try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: out))
        print("SELFCHECK ok mode=\(s.mode.rawValue) clock=\(fmtT(s.clockT)) shown=\(s.shown.count) passed=\(s.passed.count) logs=\(s.logs.count) scanned=\(s.scanned) live=\(s.live?.status ?? "-")")
        Backend.shared.stop()
        exit(0)
    }
}


/// 录制演示：AIDingPan --record 输出目录 --plan plan.json
/// 按 plan 自动操作界面，同时按 fps 截取窗口画面（jpg）并记录每帧时间，供 release/video 合成视频。
/// plan：[{"do":"page","v":"review"},{"do":"mark","v":"s3"},{"do":"wait","s":3.5},{"do":"scroll","n":2},
///        {"do":"market","v":"cn"},{"do":"replay","v":"2026-11-25","speed":3},{"do":"skip"},{"do":"selecthit"},
///        {"do":"date","v":"2026-11-24"},{"do":"watch","on":true}]
@MainActor
enum Recorder {
    static func runIfRequested(_ s: Store, _ j: JournalModel, _ m: ScreenerModel) async {
        let a = CommandLine.arguments
        guard let i = a.firstIndex(of: "--record"), i + 1 < a.count,
              let pi = a.firstIndex(of: "--plan"), pi + 1 < a.count,
              let data = FileManager.default.contents(atPath: a[pi + 1]),
              let plan = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return }
        let dir = a[i + 1]
        let fps = Double(a.firstIndex(of: "--fps").flatMap { Double(a[$0 + 1]) } ?? 12)
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        if s.bootError != nil { print("RECORD boot error"); exit(2) }
        guard let win = NSApp.windows.first(where: { $0.isVisible }), let view = win.contentView else { exit(3) }
        win.setContentSize(NSSize(width: 1600, height: 1000))
        try? await Task.sleep(nanoseconds: 1_500_000_000)
        let t0 = Date()
        var times: [Double] = [], marks: [[String: Any]] = []
        var recording = true
        let q = DispatchQueue(label: "rec", qos: .userInitiated, attributes: .concurrent)
        let group = DispatchGroup()
        let cap = Task { @MainActor in
            var n = 0
            while recording {
                let t = Date()
                // 按 1 倍分辨率截图（Retina 2 倍图渲染量是 4 倍，内容多的页面会卡到每秒 1–2 帧）
                if let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(view.bounds.width), pixelsHigh: Int(view.bounds.height),
                                              bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                              colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) {
                    rep.size = view.bounds.size
                    view.cacheDisplay(in: view.bounds, to: rep)
                    let path = String(format: "%@/f%06d.jpg", dir, n)
                    times.append(t.timeIntervalSince(t0)); n += 1
                    group.enter()
                    q.async { if let d = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.92]) { try? d.write(to: URL(fileURLWithPath: path)) }; group.leave() }
                }
                let wait = 1.0 / fps - Date().timeIntervalSince(t)
                try? await Task.sleep(nanoseconds: UInt64(max(0.005, wait) * 1e9))
            }
        }
        for step in plan {
            let v = step["v"] as? String ?? ""
            switch step["do"] as? String ?? "" {
            case "mark": marks.append(["id": v, "t": Date().timeIntervalSince(t0)])
            case "wait": try? await Task.sleep(nanoseconds: UInt64(((step["s"] as? Double) ?? 1) * 1e9))
            case "page": s.page = ["dashboard": .dashboard, "review": .review, "monitor": .monitor, "screener": .screener, "stock": .stock][v] ?? .dashboard
            case "date": j.select(v)
            case "reviewdate": await j.loadReview(v)
            case "scroll": j.scrollTo = step["n"] as? Int
            case "market": s.setMarket(v)
            case "size": s.setSize(step["n"] as? Int ?? 1500)
            case "replay":
                s.date = v
                if let sp = step["speed"] as? Int { s.speedIdx = sp }
                await s.startReplay(); s.play()
            case "skip": s.skipToEnd()
            case "selecthit":
                if let sig = s.passed.last { s.selectedID = sig.id; await s.loadSeries(for: sig) }
            case "watch": m.showWatch = step["on"] as? Bool ?? true
            default: break
            }
        }
        recording = false
        _ = await cap.value
        group.wait()
        let meta: [String: Any] = ["fps": fps, "times": times, "marks": marks, "size": [view.bounds.width, view.bounds.height]]
        if let d = try? JSONSerialization.data(withJSONObject: meta) { try? d.write(to: URL(fileURLWithPath: dir + "/meta.json")) }
        print("RECORD ok frames=\(times.count) marks=\(marks.count)")
        Backend.shared.stop()
        exit(0)
    }
}

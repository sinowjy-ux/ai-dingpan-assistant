import AppKit
import SwiftUI

// MARK: - 统计页“数据驾驶舱”：发光指标卡、信号趋势面积图、方法超额条形图、信号构成环形图

enum Neon {
    static let cyan = Color.dyn("#22D3EE", "#0891B2")
    static let violet = Color.dyn("#A78BFA", "#7C3AED")
    static let pink = Color.dyn("#F472B6", "#DB2777")
    static let gold = Color.dyn("#F5C451", "#B8860B")
    static let green = Color.dyn("#34D399", "#059669")
    static let blue = Color.dyn("#60A5FA", "#2563EB")
    static let red = Color.dyn("#F87171", "#DC2626")
}

/// 玻璃质感卡片：深色渐变底 + 彩色渐变描边 + 柔光
struct GlowCard: ViewModifier {
    var colors: [Color]
    var radius: CGFloat = 16
    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: radius)
                    .fill(LinearGradient(colors: [Theme.cardA, Theme.cardB], startPoint: .topLeading, endPoint: .bottomTrailing))
            )
            .overlay(
                ZStack {   // 多层描边模拟霓虹光晕（比 shadow 模糊便宜得多，录屏/截图不卡）
                    RoundedRectangle(cornerRadius: radius + 3).stroke((colors.first ?? .clear).opacity(0.10), lineWidth: 6).padding(-3)
                    RoundedRectangle(cornerRadius: radius + 1).stroke((colors.first ?? .clear).opacity(0.18), lineWidth: 3).padding(-1)
                    RoundedRectangle(cornerRadius: radius)
                        .stroke(LinearGradient(colors: colors.map { $0.opacity(0.95) } + [Theme.line],
                                               startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1.3)
                }
                .allowsHitTesting(false)
            )
    }
}
extension View {
    func glow(_ colors: [Color], radius: CGFloat = 16) -> some View { modifier(GlowCard(colors: colors, radius: radius)) }
}

/// 迷你走势线
struct Spark: View {
    let values: [Double]
    let color: Color
    var body: some View {
        Canvas { ctx, size in
            guard values.count > 1, let mx = values.max(), mx > 0 else { return }
            let pts = values.enumerated().map { i, v in
                CGPoint(x: size.width * CGFloat(i) / CGFloat(values.count - 1), y: size.height * (1 - CGFloat(v / mx)) * 0.85 + 2)
            }
            var line = Path(); line.addLines(pts)
            var area = line; area.addLine(to: CGPoint(x: size.width, y: size.height)); area.addLine(to: CGPoint(x: 0, y: size.height)); area.closeSubpath()
            ctx.fill(area, with: .linearGradient(Gradient(colors: [color.opacity(0.45), color.opacity(0)]), startPoint: .zero, endPoint: CGPoint(x: 0, y: size.height)))
            ctx.stroke(line, with: .color(color), style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
            if let l = pts.last { ctx.fill(Path(ellipseIn: CGRect(x: l.x - 3, y: l.y - 3, width: 6, height: 6)), with: .color(color)) }
        }
    }
}

struct NeonKpi: View {
    let icon: String, title: String, value: String, sub: String
    let color: Color
    var spark: [Double] = []
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 13, weight: .bold)).foregroundColor(color)
                    .frame(width: 28, height: 28)
                    .background(Circle().fill(color.opacity(0.16)))
                Text(title).font(.system(size: 12, weight: .medium)).foregroundColor(Theme.dim)
                Spacer(minLength: 0)
            }
            Text(value).font(.system(size: 30, weight: .heavy, design: .rounded))
                .foregroundStyle(LinearGradient(colors: [Theme.hi, color], startPoint: .top, endPoint: .bottom))
                .lineLimit(1).minimumScaleFactor(0.5)
            HStack(alignment: .bottom) {
                Text(sub).font(.system(size: 10.5)).foregroundColor(Theme.faint).lineLimit(1)
                Spacer(minLength: 4)
                if spark.count > 1 { Spark(values: spark, color: color).frame(width: 64, height: 22) }
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .glow([color, color.opacity(0.2)], radius: 14)
    }
}

struct DashHero: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        let sm = j.summary
        let ds = sm["dates"].arr.reversed().map { $0 }      // 升序
        let scr = ds.map { Double($0["screener"].int) }, mon = ds.map { Double($0["monitor"].int) }
        let tot = zip(scr, mon).map { $0 + $1 }
        let ms = sm["methods"].arr
        let n1 = ms.reduce(0) { $0 + $1["n1"].int }
        let wins = ms.reduce(0.0) { $0 + ($1["win1"].num ?? 0) * Double($1["n1"].int) / 100 }
        let winRate = n1 > 0 ? wins / Double(n1) * 100 : 0
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 10) {
                    Image(systemName: "chart.xyaxis.line").font(.system(size: 22, weight: .bold))
                        .foregroundStyle(LinearGradient(colors: [Neon.cyan, Neon.violet], startPoint: .leading, endPoint: .trailing))
                    Text("数据驾驶舱").font(.system(size: 30, weight: .heavy))
                        .foregroundStyle(LinearGradient(colors: [Theme.hi, Neon.cyan], startPoint: .leading, endPoint: .trailing))
                }
                Text("选股 · 盯盘 · 复盘 全部入库，次日自动比对").font(.system(size: 12.5)).foregroundColor(Theme.dim).lineLimit(1)
                HStack(spacing: 6) {
                    if !sm["app"].isNull {
                        Text("v\(sm["app"]["version"].str) \(sm["app"]["channel"].str)").font(.system(size: 10, weight: .bold))
                            .foregroundColor(Neon.cyan).padding(.horizontal, 6).padding(.vertical, 1)
                            .overlay(Capsule().stroke(Neon.cyan.opacity(0.7)))
                            .help("构建号 \(sm["app"]["build"].str)；反馈问题时请注明版本号")
                    }
                }
                TimelineView(.periodic(from: .now, by: 1)) { _ in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(beijingString("HH:mm:ss")).font(.system(size: 34, weight: .bold, design: .monospaced))
                            .foregroundStyle(LinearGradient(colors: [Theme.hi, Neon.cyan], startPoint: .top, endPoint: .bottom))
                        Text("北京时间\n\(beijingString("MM-dd EEE"))").font(.system(size: 10.5)).foregroundColor(Theme.dim)
                    }
                }
                HStack(spacing: 8) {
                    Button { Task { await j.evaluate() } } label: { Label("更新比对", systemImage: "arrow.triangle.2.circlepath") }
                        .help("用最新行情计算之前选出股票的 T+1/T+3/T+5 表现")
                    Button { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: j.summary["db_path"].str)]) } label: {
                        Image(systemName: "folder")
                    }
                    .help("在访达中显示数据库（SQLite，复制即可备份）")
                    Button { Task { await j.load() } } label: { Image(systemName: "arrow.clockwise") }.help("刷新")
                }
                .controlSize(.small)
            }
            .frame(width: 300, alignment: .leading)
            NeonKpi(icon: "calendar", title: "数据天数", value: "\(sm["days"].int)",
                    sub: sm["first"].isNull ? "—" : "\(sm["first"].str) 起", color: Neon.blue, spark: tot)
            NeonKpi(icon: "scope", title: "主力选股", value: grouped(Int(scr.reduce(0, +))), sub: "每次扫描自动入库", color: Neon.gold, spark: scr)
            NeonKpi(icon: "waveform.path.ecg", title: "盯盘信号", value: grouped(Int(mon.reduce(0, +))), sub: "实盘自动 / 回放手动", color: Neon.green, spark: mon)
            NeonKpi(icon: "checkmark.seal", title: "已比对", value: grouped(sm["tracked"].int), sub: "有 T+1 结果", color: Neon.cyan)
            NeonKpi(icon: "target", title: "T+1 胜率", value: n1 > 0 ? String(format: "%.0f%%", winRate) : "—",
                    sub: "全部方法 \(grouped(n1)) 条", color: Neon.violet)
            NeonKpi(icon: "star.fill", title: "研判 · 收藏", value: "\(sm["counts"]["analyses"].int) · \(sm["counts"]["favorites"].int)",
                    sub: "个股研判次数 · ★ 收藏", color: Neon.pink)
        }
    }
}

/// 每日信号趋势（主力选股 / AI 盯盘 两条面积）
struct TrendCard: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        let ds = j.summary["dates"].arr.reversed().map { $0 }
        let scr = ds.map { Double($0["screener"].int) }, mon = ds.map { Double($0["monitor"].int) }
        let labels = ds.map { String($0["date"].str.suffix(5)) }
        let mx = max(1, (scr + mon).max() ?? 1)
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("每日信号趋势").font(.system(size: 14, weight: .bold))
                Spacer()
                legend("主力选股", Neon.gold); legend("AI 盯盘", Neon.green)
            }
            if ds.count < 2 {
                Spacer(); Text("积累两天以上数据后显示趋势").font(.system(size: 12)).foregroundColor(Theme.faint).frame(maxWidth: .infinity); Spacer()
            } else {
                Canvas { ctx, size in
                    let h = size.height - 18, w = size.width
                    for g in 0...3 {     // 网格
                        let y = h * CGFloat(g) / 3
                        var p = Path(); p.move(to: CGPoint(x: 0, y: y)); p.addLine(to: CGPoint(x: w, y: y))
                        ctx.stroke(p, with: .color(Theme.grid), lineWidth: 1)
                    }
                    func draw(_ v: [Double], _ c: Color) {
                        let pts = v.enumerated().map { CGPoint(x: w * CGFloat($0) / CGFloat(v.count - 1), y: h * (1 - CGFloat($1 / mx)) + 2) }
                        var line = Path(); line.move(to: pts[0])
                        for i in 1..<pts.count {      // 平滑曲线
                            let a = pts[i - 1], b = pts[i], m = (a.x + b.x) / 2
                            line.addCurve(to: b, control1: CGPoint(x: m, y: a.y), control2: CGPoint(x: m, y: b.y))
                        }
                        var area = line; area.addLine(to: CGPoint(x: w, y: h)); area.addLine(to: CGPoint(x: 0, y: h)); area.closeSubpath()
                        ctx.fill(area, with: .linearGradient(Gradient(colors: [c.opacity(0.42), c.opacity(0.02)]), startPoint: .zero, endPoint: CGPoint(x: 0, y: h)))
                        ctx.stroke(line, with: .color(c), style: StrokeStyle(lineWidth: 2.2, lineCap: .round))
                        for p in pts { ctx.fill(Path(ellipseIn: CGRect(x: p.x - 3, y: p.y - 3, width: 6, height: 6)), with: .color(c)) }
                    }
                    draw(scr, Neon.gold); draw(mon, Neon.green)
                    for (i, l) in labels.enumerated() where labels.count <= 12 || i % max(1, labels.count / 8) == 0 {
                        let x = w * CGFloat(i) / CGFloat(labels.count - 1)
                        ctx.draw(Text(l).font(.system(size: 9.5, design: .monospaced)).foregroundColor(Theme.faint),
                                 at: CGPoint(x: min(max(x, 16), w - 16), y: size.height - 6))
                    }
                }
            }
        }
        .padding(14).frame(maxWidth: .infinity, maxHeight: .infinity).glow([Neon.gold, Neon.green])
    }
    func legend(_ t: String, _ c: Color) -> some View {
        HStack(spacing: 4) { Circle().fill(c).frame(width: 7, height: 7); Text(t).font(.system(size: 11)).foregroundColor(Theme.dim) }
    }
}

/// 各方法 T+1 超额收益（相对大盘），正红负绿，居中对称
struct ExcessCard: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        let all = j.summary["methods"].arr.filter { $0["n1"].int >= 5 && $0["ex1"].num != nil }
            .sorted { ($0["ex1"].num ?? 0) > ($1["ex1"].num ?? 0) }
        let ms = all.count <= 9 ? all : Array(all.prefix(5)) + Array(all.suffix(4))   // 最好 5 个 + 最差 4 个
        let mx = max(0.5, ms.map { abs($0["ex1"].num ?? 0) }.max() ?? 1)
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text("方法实盘战绩").font(.system(size: 14, weight: .bold))
                Text("T+1 超额（相对大盘）").font(.system(size: 11)).foregroundColor(Theme.dim)
                Spacer()
                Text("样本 ≥ 5 条").font(.system(size: 10.5)).foregroundColor(Theme.faint)
            }
            if ms.isEmpty {
                Spacer(); Text("比对数据积累后显示").font(.system(size: 12)).foregroundColor(Theme.faint).frame(maxWidth: .infinity); Spacer()
            }
            ForEach(ms, id: \.self) { m in
                let ex = m["ex1"].num ?? 0
                let src = m["source"].str == "screener" ? "选" : (m["market"].str == "us" ? "盯美" : "盯")
                HStack(spacing: 8) {
                    HStack(spacing: 4) {
                        Text(src).font(.system(size: 9.5, weight: .bold)).foregroundColor(Theme.faint)
                        Text(m["method"].str).font(.system(size: 11.5, weight: .semibold)).lineLimit(1)
                        Text(m["tier"].str).font(.system(size: 9.5)).foregroundColor(m["tier"].str == "命中" || m["tier"].str == "已验证" ? Neon.gold : Theme.faint)
                    }
                    .frame(width: 168, alignment: .leading)
                    GeometryReader { g in
                        let half = g.size.width / 2, len = half * CGFloat(abs(ex) / mx)
                        ZStack(alignment: .leading) {
                            Rectangle().fill(Theme.line).frame(width: 1).offset(x: half)
                            RoundedRectangle(cornerRadius: 4)
                                .fill(LinearGradient(colors: ex >= 0 ? [Neon.red.opacity(0.5), Neon.red] : [Neon.green, Neon.green.opacity(0.5)],
                                                     startPoint: .leading, endPoint: .trailing))
                                .frame(width: max(2, len), height: 12)
                                .offset(x: ex >= 0 ? half : half - len)
                        }
                        .frame(height: g.size.height)
                    }
                    .frame(height: 16)
                    Text(signed(ex)).font(monoF(11.5, .bold)).foregroundColor(ex >= 0 ? Neon.red : Neon.green).frame(width: 58, alignment: .trailing)
                    Text("\(m["n1"].int)").font(monoF(10)).foregroundColor(Theme.faint).frame(width: 30, alignment: .trailing)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(14).frame(maxWidth: .infinity, maxHeight: .infinity).glow([Neon.violet, Neon.red])
    }
}

/// 信号构成环形图
struct CompositionCard: View {
    @EnvironmentObject var j: JournalModel
    func sum(_ src: String, _ tier: String) -> Double {
        Double(j.summary["methods"].arr.filter { $0["source"].str == src && $0["tier"].str == tier }.reduce(0) { $0 + $1["n"].int })
    }
    var body: some View {
        let parts: [(String, Double, Color)] = [("选股 · 已验证", sum("screener", "已验证"), Neon.gold),
                                                 ("选股 · 观察", sum("screener", "未验证"), Neon.blue),
                                                 ("盯盘 · 命中", sum("monitor", "命中"), Neon.green),
                                                 ("盯盘 · 剔除", sum("monitor", "剔除"), Color(hex: "#475569"))]
        let total = max(1, parts.reduce(0) { $0 + $1.1 })
        VStack(alignment: .leading, spacing: 8) {
            Text("信号构成").font(.system(size: 14, weight: .bold))
            HStack(spacing: 14) {
                ZStack {
                    Canvas { ctx, size in
                        let r = min(size.width, size.height) / 2 - 8
                        let c = CGPoint(x: size.width / 2, y: size.height / 2)
                        var a = -Double.pi / 2
                        for p in parts where p.1 > 0 {
                            let e = a + 2 * Double.pi * p.1 / total
                            var path = Path()
                            path.addArc(center: c, radius: r, startAngle: .radians(a + 0.02), endAngle: .radians(e - 0.02), clockwise: false)
                            ctx.stroke(path, with: .color(p.2), style: StrokeStyle(lineWidth: 16, lineCap: .butt))
                            a = e
                        }
                    }
                    VStack(spacing: 0) {
                        Text(grouped(Int(total))).font(.system(size: 24, weight: .heavy, design: .rounded)).foregroundColor(Theme.ink)
                        Text("条记录").font(.system(size: 10.5)).foregroundColor(Theme.dim)
                    }
                }
                .frame(width: 130, height: 130)
                VStack(alignment: .leading, spacing: 9) {
                    ForEach(parts, id: \.0) { p in
                        HStack(spacing: 6) {
                            RoundedRectangle(cornerRadius: 2).fill(p.2).frame(width: 9, height: 9)
                            Text(p.0).font(.system(size: 11.5)).foregroundColor(Theme.dim)
                            Spacer(minLength: 4)
                            Text(grouped(Int(p.1))).font(monoF(12, .bold))
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(14).frame(maxWidth: .infinity, maxHeight: .infinity).glow([Neon.cyan, Neon.blue])
    }
}

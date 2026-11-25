import AppKit
import SwiftUI

// MARK: - 统计页（App 第一页）：数据库总览、按天查询、方法实盘表现、收藏、数据管理

struct DashboardPage: View {
    @EnvironmentObject var j: JournalModel
    @EnvironmentObject var s: Store
    var body: some View {
        VStack(spacing: 12) {
            DashHero().frame(height: 156)
            if !j.summary["init"].isNull && !j.summary["init"]["ready"].bool {
                let I = j.summary["init"]
                VStack(alignment: .leading, spacing: 4) {
                    Text("首次使用：正在下载近 5 年历史日K（约 10–25 分钟），已完成 \(I["klines"].int) / 约 5000 只")
                        .font(.system(size: 13, weight: .bold)).foregroundColor(Theme.yellow)
                    Text(I["scanning"].bool ? "下载完成后会自动扫描一次，主力选股、AI 盯盘（A股）和比对功能就可以用了。期间可以先看每日复盘。"
                         : "当前没有在下载：到“主力选股”页点“更新行情并扫描”即可开始。")
                        .font(.system(size: 12)).foregroundColor(Theme.dim)
                    Text(I["log"].str.split(separator: "\n").suffix(2).joined(separator: "\n")).font(monoF(10.5)).foregroundColor(Theme.faint)
                }
                .padding(12).frame(maxWidth: .infinity, alignment: .leading).panel(glow: Theme.yellow)
                .task(id: I["log"].str + String(I["klines"].int)) { try? await Task.sleep(nanoseconds: 8_000_000_000); await j.load() }
            }
            HStack(spacing: 12) {
                TrendCard()
                ExcessCard().frame(width: 560)
                CompositionCard().frame(width: 330)
            }
            .frame(height: 250)
            HStack(alignment: .top, spacing: 12) {
                DateList().frame(width: 210)
                DayPanel()
                ScrollView {
                    VStack(spacing: 10) {
                        MethodPerf()
                        FavPanel()
                        DeletePanel()
                    }
                }
                .frame(width: 450)
            }
        }
        .background(
            ZStack {
                RadialGradient(colors: [Neon.cyan.opacity(0.10), .clear], center: .topLeading, startRadius: 10, endRadius: 700)
                RadialGradient(colors: [Neon.violet.opacity(0.10), .clear], center: .topTrailing, startRadius: 10, endRadius: 700)
            }
            .allowsHitTesting(false)      // 背景光晕不能挡住上方导航条的点击
        )
        .task { await j.load() }
    }
}

struct Kpi: View {
    let title: String, value: String
    var sub: String = ""
    var color: Color = Theme.ink
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 11.5)).foregroundColor(Theme.dim)
            Text(value).font(monoF(22, .bold)).foregroundColor(color).lineLimit(1).minimumScaleFactor(0.6)
            Text(sub).font(.system(size: 10.5)).foregroundColor(Theme.faint).lineLimit(1)
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .frame(minWidth: 118, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.panel2))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.line))
    }
}

struct DashHeader: View {
    @EnvironmentObject var j: JournalModel
    @EnvironmentObject var s: Store
    var body: some View {
        let sm = j.summary
        let c = sm["counts"]
        let mon = sm["dates"].arr.reduce(0) { $0 + $1["monitor"].int }
        let scr = sm["dates"].arr.reduce(0) { $0 + $1["screener"].int }
        HStack(alignment: .center, spacing: 14) {
            Text("统").font(.system(size: 26, weight: .bold)).foregroundColor(Theme.blue)
                .frame(width: 60, height: 60)
                .background(RoundedRectangle(cornerRadius: 14).fill(Theme.blue.opacity(0.06)))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.blue.opacity(0.85), lineWidth: 1.5))
            VStack(alignment: .leading, spacing: 4) {
                Text("数据统计").font(.system(size: 24, weight: .semibold))
                Text("本地数据库 · \(String(format: "%.1f", Double(sm["db_size"].int) / 1_048_576)) MB")
                    .font(.system(size: 12)).foregroundColor(Theme.dim)
                Text(sm["db_path"].str).font(monoF(10)).foregroundColor(Theme.faint).lineLimit(1).textSelection(.enabled)
            }
            .frame(width: 250, alignment: .leading)
            Kpi(title: "数据天数", value: "\(sm["days"].int)", sub: sm["first"].isNull ? "—" : "\(sm["first"].str) 起")
            Kpi(title: "主力选股记录", value: grouped(scr), sub: "每次扫描自动保存", color: Theme.yellow)
            Kpi(title: "盯盘信号", value: grouped(mon), sub: "实盘自动 / 回放手动", color: Theme.green)
            Kpi(title: "已比对", value: grouped(sm["tracked"].int), sub: "有 T+1 结果的条数", color: Theme.blue)
            Kpi(title: "复盘", value: "\(c["reviews"].int) 篇", sub: "盘前 9:00 / 收盘 15:35 自动")
            Kpi(title: "收藏", value: "\(c["favorites"].int)", sub: "★ 标记的股票", color: Theme.gold)
            Spacer(minLength: 6)
            VStack(alignment: .trailing, spacing: 6) {
                TimelineView(.periodic(from: .now, by: 1)) { _ in
                    Text(beijingString("HH:mm:ss")).font(.system(size: 28, weight: .bold, design: .monospaced))
                }
                HStack(spacing: 8) {
                    Button { Task { await j.evaluate() } } label: { Label("更新比对", systemImage: "arrow.triangle.2.circlepath") }
                        .help("用最新行情计算之前选出股票的 T+1/T+3/T+5 表现")
                    Button { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: j.summary["db_path"].str)]) } label: {
                        Label("在访达中显示数据库", systemImage: "folder")
                    }
                    .help("SQLite 文件，可用 DB Browser for SQLite 打开；复制这个文件即可备份")
                    Button { Task { await j.load() } } label: { Image(systemName: "arrow.clockwise") }.help("刷新")
                }
            }
        }
        .padding(14).panel()
    }
}

struct DateList: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "按天查询", trailing: "\(j.dates.count) 天")
            if j.dates.isEmpty {
                Spacer()
                Text("数据库还是空的\n扫描一次主力选股就会自动存入").multilineTextAlignment(.center)
                    .font(.system(size: 12)).foregroundColor(Theme.dim).frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing: 4) {
                        ForEach(j.dates, id: \.self) { d in
                            let ds = d["date"].str
                            let sel = ds == j.date
                            Button { j.select(ds) } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack {
                                        Text(ds).font(monoF(13, .semibold))
                                        Text(weekday(ds)).font(.system(size: 10.5)).foregroundColor(Theme.dim)
                                        Spacer()
                                        if !d["review"].isNull && d["review"].str != "false" {
                                            Text(d["review"].str).font(.system(size: 9.5, weight: .bold)).foregroundColor(Theme.blue)
                                                .padding(.horizontal, 5).padding(.vertical, 1)
                                                .overlay(Capsule().stroke(Theme.blue.opacity(0.7)))
                                        }
                                    }
                                    HStack(spacing: 8) {
                                        badge("选", d["screener"].int, Theme.yellow)
                                        badge("盯", d["monitor"].int, Theme.green)
                                        if d["stock"].int > 0 { badge("研", d["stock"].int, Neon.pink) }
                                        if d["favorites"].int > 0 { badge("★", d["favorites"].int, Theme.gold) }
                                        Spacer()
                                    }
                                }
                                .padding(.horizontal, 10).padding(.vertical, 7)
                                .background(RoundedRectangle(cornerRadius: 7).fill(sel ? Theme.blue.opacity(0.16) : Theme.panel2.opacity(0.6)))
                                .overlay(RoundedRectangle(cornerRadius: 7).stroke(sel ? Theme.blue.opacity(0.8) : Color.clear))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
        .padding(12).frame(maxHeight: .infinity, alignment: .top).glow([Neon.blue.opacity(0.7)], radius: 14)
    }
    func badge(_ t: String, _ n: Int, _ c: Color) -> some View {
        HStack(spacing: 3) {
            Text(t).font(.system(size: 10, weight: .bold)).foregroundColor(n > 0 ? c : Theme.faint)
            Text("\(n)").font(monoF(10.5)).foregroundColor(n > 0 ? Theme.ink : Theme.faint)
        }
    }
}

func weekday(_ d: String) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "Asia/Shanghai")
    guard let x = f.date(from: d) else { return "" }
    var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "Asia/Shanghai")!
    return ["", "周日", "周一", "周二", "周三", "周四", "周五", "周六"][cal.component(.weekday, from: x)]
}

struct DayPanel: View {
    @EnvironmentObject var j: JournalModel
    @EnvironmentObject var s: Store
    var body: some View {
        let picks = j.day["picks"].arr.filter { j.sourceFilter == "all" || $0["source"].str == j.sourceFilter }
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(j.date.isEmpty ? "—" : j.date).font(.system(size: 20, weight: .bold, design: .monospaced))
                Text(weekday(j.date)).foregroundColor(Theme.dim)
                Spacer()
                Picker("", selection: $j.sourceFilter) {
                    Text("全部").tag("all"); Text("主力选股").tag("screener"); Text("AI 盯盘").tag("monitor"); Text("个股研判").tag("stock")
                }
                .pickerStyle(.segmented).labelsHidden().frame(width: 240)
            }
            if !j.day["review"].isNull {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("当日复盘 · \(j.day["review"]["kind"].str)").font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.blue)
                        Text("生成于 \(j.day["review"]["created"].str)").font(.system(size: 11)).foregroundColor(Theme.faint)
                        Spacer()
                        Button("打开复盘 →") { s.page = .review; Task { await j.loadReview(j.date) } }.buttonStyle(.link)
                    }
                    Text(j.day["review"]["summary"].str).font(.system(size: 12)).foregroundColor(Theme.ink.opacity(0.85))
                        .lineLimit(5).fixedSize(horizontal: false, vertical: true)
                }
                .padding(10).background(RoundedRectangle(cornerRadius: 8).fill(Theme.blue.opacity(0.06)))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.blue.opacity(0.35)))
            }
            let an = j.day["analyses"].arr
            if !an.isEmpty && (j.sourceFilter == "all" || j.sourceFilter == "stock") {
                AnalysesList(items: an, fill: j.sourceFilter == "stock")
            }
            if j.sourceFilter != "stock" {
            DayMethods(methods: j.day["methods"].arr.filter { j.sourceFilter == "all" || $0["source"].str == j.sourceFilter })
            PickHeader()
            if picks.isEmpty {
                Spacer()
                Text("这一天没有\(j.sourceFilter == "monitor" ? "盯盘信号" : (j.sourceFilter == "screener" ? "选股记录" : "记录"))")
                    .foregroundColor(Theme.dim).frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView { LazyVStack(spacing: 2) { ForEach(picks, id: \.self) { PickRow(p: $0) } } }
            }
            } else if an.isEmpty {
                Spacer(); Text("这一天没有个股研判记录").foregroundColor(Theme.dim).frame(maxWidth: .infinity); Spacer()
            }
        }
        .padding(14).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).glow([Neon.cyan.opacity(0.7)], radius: 14)
    }
}

struct DayMethods: View {
    let methods: [JV]
    var body: some View {
        if !methods.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(methods, id: \.self) { m in
                    let r1 = m["r1"]
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 4) {
                            Text(m["method"].str).font(.system(size: 12, weight: .semibold))
                                .foregroundColor(m["source"].str == "screener" ? Color(hex: SCR_COLORS[m["method"].str] ?? "#5B8DEF") : Theme.green)
                            Text(m["tier"].str).font(.system(size: 9.5)).foregroundColor(Theme.dim)
                            Spacer()
                            Text("\(m["n"].int)只").font(monoF(10.5)).foregroundColor(Theme.dim)
                        }
                        HStack(spacing: 6) {
                            if r1.isNull && !m["r0"].isNull {
                                Text("当日收 \(pctText(m["r0"]))").font(monoF(11, .semibold)).foregroundColor(Theme.up(m["r0"].num ?? 0))
                                Text("T+1 待比对").font(monoF(10.5)).foregroundColor(Theme.faint)
                            } else {
                            Text("T+1 \(pctText(r1))").font(monoF(11, .semibold)).foregroundColor(Theme.up(r1.num ?? 0))
                            Text("胜率 \(m["win1"].num.map { String(format: "%.0f%%", $0) } ?? "—")").font(monoF(10.5)).foregroundColor(Theme.dim)
                            Text("超额 \(pctText(m["ex1"]))").font(monoF(10.5)).foregroundColor(Theme.up(m["ex1"].num ?? 0))
                            }
                        }
                    }
                    .padding(.horizontal, 8).padding(.vertical, 5)
                    .frame(width: 180, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Theme.panel2))
                }
            }
            }
        }
    }
}

struct PickHeader: View {
    var body: some View {
        HStack(spacing: 0) {
            Text("").frame(width: 22)
            Text("股票").frame(width: 128, alignment: .leading)
            Text("来源 · 方法").frame(width: 140, alignment: .leading)
            Text("等级").frame(width: 50, alignment: .leading)
            Text("信号价").frame(width: 60, alignment: .trailing)
            Text("当日收").frame(width: 56, alignment: .trailing)
            Text("T+1").frame(width: 56, alignment: .trailing)
            Text("T+3").frame(width: 56, alignment: .trailing)
            Text("T+5").frame(width: 56, alignment: .trailing)
            Text("超额T+1").frame(width: 62, alignment: .trailing)
            Text("5日最高").frame(width: 58, alignment: .trailing)
            Text("止损").frame(width: 56, alignment: .trailing)
            Spacer(minLength: 0)
        }
        .font(.system(size: 11)).foregroundColor(Theme.dim).padding(.horizontal, 6)
    }
}

struct PickRow: View {
    @EnvironmentObject var j: JournalModel
    let p: JV
    var body: some View {
        let src = p["source"].str
        let isMon = src == "monitor"
        let c = isMon ? Theme.green : Color(hex: SCR_COLORS[p["method"].str] ?? "#5B8DEF")
        let ex1: Double? = { guard let a = p["r1"].num, let b = p["b1"].num else { return nil }; return a - b }()
        HStack(spacing: 0) {
            FavStar(source: src, market: p["market"].str, date: p["date"].str, code: p["code"].str, name: p["name"].str,
                    method: p["method"].str, price: p["price"].num, size: 12).frame(width: 22, alignment: .leading)
            HStack(spacing: 5) {
                Text(p["name"].str).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                Text(p["code"].str).font(monoF(10)).foregroundColor(Theme.dim)
            }
            .frame(width: 128, alignment: .leading)
            HStack(spacing: 4) {
                Text(isMon ? "盯\(p["market"].str == "us" ? "·美" : "") \(p["time"].str)" : "选").font(.system(size: 10, weight: .bold)).foregroundColor(Theme.dim)
                Text(p["method"].str).font(.system(size: 12, weight: .semibold)).foregroundColor(c).lineLimit(1)
            }
            .frame(width: 140, alignment: .leading)
            Group {
                if isMon {
                    Text("\(p["grade"].str) \(p["score"].int)").font(monoF(11.5, .bold)).foregroundColor(p["validated"].bool ? Theme.grade(p["grade"].str) : Theme.faint)
                } else {
                    Text(p["validated"].bool ? "✓ 验证" : "\(p["score"].int)").font(monoF(11.5, .bold)).foregroundColor(p["validated"].bool ? Theme.green : Theme.dim)
                }
            }
            .frame(width: 50, alignment: .leading)
            Text(p["price"].num.map { String(format: "%.2f", $0) } ?? "—").font(monoF(11.5)).frame(width: 60, alignment: .trailing)
            cell(isMon ? p["r0"] : .null).frame(width: 56, alignment: .trailing)
            cell(p["r1"]).frame(width: 56, alignment: .trailing)
            cell(p["r3"]).frame(width: 56, alignment: .trailing)
            cell(p["r5"]).frame(width: 56, alignment: .trailing)
            Text(ex1.map { signed($0) } ?? "—").font(monoF(11.5)).foregroundColor(Theme.up(ex1 ?? 0)).frame(width: 62, alignment: .trailing)
            cell(p["max5"]).frame(width: 58, alignment: .trailing)
            Text(p["stop_hit"].int == 1 ? "破止损" : (p["stop"].num.map { String(format: "%.2f", $0) } ?? "—"))
                .font(monoF(11)).foregroundColor(p["stop_hit"].int == 1 ? Theme.red : Theme.faint)
                .lineLimit(1).frame(width: 56, alignment: .trailing)
            Spacer(minLength: 0)
        }
        .padding(.vertical, 5).padding(.horizontal, 6)
        .background(RoundedRectangle(cornerRadius: 5).fill(p["validated"].bool ? (isMon ? Theme.gold.opacity(0.06) : Theme.green.opacity(0.05)) : Color.clear))
        .help(p["note"].str)
    }
    func cell(_ v: JV) -> some View {
        Text(v.num.map { signed($0) } ?? "—").font(monoF(11.5)).foregroundColor(v.num == nil ? Theme.faint : Theme.up(v.num!))
    }
}

struct MethodPerf: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        let ms = j.summary["methods"].arr
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "方法实盘跟踪（全部日期 · 样本外）", trailing: "超额 = 个股 − 同期大盘")
            Text("每天保存的选股，之后真实走势的统计。这是回测之外的“样本外检验”：样本越多越可信，T+1 至少 100 条再下结论；个别暴涨股会拉高平均，同时看中位数。")
                .font(.system(size: 11)).foregroundColor(Theme.dim).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 0) {
                Text("方法").frame(maxWidth: .infinity, alignment: .leading)
                Text("条数").frame(width: 38, alignment: .trailing)
                Text("T+1").frame(width: 56, alignment: .trailing)
                Text("中位").frame(width: 54, alignment: .trailing)
                Text("胜率").frame(width: 40, alignment: .trailing)
                Text("超额").frame(width: 56, alignment: .trailing)
            }
            .font(.system(size: 10.5)).foregroundColor(Theme.dim)
            if ms.isEmpty { Text("还没有数据").font(.system(size: 12)).foregroundColor(Theme.faint) }
            ForEach(ms, id: \.self) { m in
                let src = m["source"].str
                HStack(spacing: 0) {
                    HStack(spacing: 4) {
                        Text(src == "screener" ? "选" : (m["market"].str == "us" ? "盯美" : "盯")).font(.system(size: 9.5, weight: .bold)).foregroundColor(Theme.faint)
                        Text(m["method"].str).font(.system(size: 12, weight: .semibold))
                            .foregroundColor(src == "screener" ? Color(hex: SCR_COLORS[m["method"].str] ?? "#5B8DEF") : Theme.green)
                            .lineLimit(1).minimumScaleFactor(0.8).layoutPriority(1)
                        Text(m["tier"].str).font(.system(size: 9.5)).foregroundColor(m["tier"].str == "命中" || m["tier"].str == "已验证" ? Theme.gold : Theme.faint)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Text("\(m["n1"].int)").font(monoF(11)).foregroundColor(Theme.dim).frame(width: 38, alignment: .trailing)
                    Text(pctText(m["r1"])).font(monoF(11.5, .semibold)).foregroundColor(Theme.up(m["r1"].num ?? 0)).frame(width: 56, alignment: .trailing)
                    Text(pctText(m["med1"])).font(monoF(11)).foregroundColor(Theme.up(m["med1"].num ?? 0)).frame(width: 54, alignment: .trailing)
                    Text(m["win1"].num.map { String(format: "%.0f%%", $0) } ?? "—").font(monoF(11)).frame(width: 40, alignment: .trailing)
                    Text(pctText(m["ex1"])).font(monoF(11)).foregroundColor(Theme.up(m["ex1"].num ?? 0)).frame(width: 56, alignment: .trailing)
                }
                .padding(.vertical, 2)
            }
        }
        .padding(14).panel()
    }
}

struct FavPanel: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        let fs = j.summary["favorites"].arr
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "★ 收藏", trailing: "\(fs.count) 只")
            if fs.isEmpty {
                Text("在主力选股、AI 盯盘、统计页点 ☆ 收藏").font(.system(size: 12)).foregroundColor(Theme.faint)
            }
            ForEach(fs, id: \.self) { f in
                HStack(spacing: 8) {
                    FavStar(source: f["source"].str, market: f["market"].str, date: f["date"].str, code: f["code"].str,
                            name: f["name"].str, method: f["method"].str, size: 12)
                    VStack(alignment: .leading, spacing: 1) {
                        HStack(spacing: 5) {
                            Text(f["name"].str).font(.system(size: 12.5, weight: .semibold))
                            Text(f["code"].str).font(monoF(10)).foregroundColor(Theme.dim)
                        }
                        Text("\(f["date"].str) · \(["monitor": "盯盘", "stock": "研判"][f["source"].str] ?? "选股") · \(f["method"].str)")
                            .font(.system(size: 10.5)).foregroundColor(Theme.dim).lineLimit(1)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 1) {
                        Text("T+1 \(pctText(f["r1"]))").font(monoF(11)).foregroundColor(Theme.up(f["r1"].num ?? 0))
                        Text("T+5 \(pctText(f["r5"]))").font(monoF(10.5)).foregroundColor(Theme.up(f["r5"].num ?? 0))
                    }
                }
                .padding(.vertical, 3)
                .contentShape(Rectangle())
                .onTapGesture { j.select(f["date"].str) }
            }
        }
        .padding(14).panel()
    }
}

struct DeletePanel: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "数据管理 · 删除", trailing: "不可恢复")
            HStack(spacing: 8) {
                Picker("", selection: Binding(get: { j.delUnit }, set: { j.delUnit = $0; j.delValue = j.defaultDelValue(); j.delPreview = .null })) {
                    ForEach(DelUnit.allCases) { Text($0.label).tag($0) }
                }
                .labelsHidden().frame(width: 130)
                TextField(placeholder, text: Binding(get: { j.delValue }, set: { j.delValue = $0; j.delPreview = .null }))
                    .textFieldStyle(.roundedBorder).font(monoF(12)).frame(width: 120)
                Button("预览") { Task { await j.previewDelete() } }
            }
            HStack(spacing: 12) {
                ForEach([("picks", "选股/盯盘"), ("reviews", "复盘"), ("favorites", "收藏"), ("analyses", "研判记录")], id: \.0) { k, t in
                    Toggle(t, isOn: Binding(get: { j.delWhat.contains(k) }, set: { v in
                        if v { j.delWhat.insert(k) } else { j.delWhat.remove(k) }; j.delPreview = .null }))
                    .toggleStyle(.checkbox).font(.system(size: 12))
                }
            }
            Text(hint).font(.system(size: 10.5)).foregroundColor(Theme.faint)
            if !j.delPreview.isNull {
                let c = j.delPreview["counts"]
                let total = c["picks"].int + c["reviews"].int + c["favorites"].int
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(j.delPreview["from"].str) ~ \(j.delPreview["to"].str)").font(monoF(12, .semibold))
                        Text("选股/盯盘 \(c["picks"].int) 条 · 复盘 \(c["reviews"].int) 篇 · 收藏 \(c["favorites"].int) 条")
                            .font(.system(size: 11.5)).foregroundColor(Theme.dim)
                    }
                    Spacer()
                    Button(role: .destructive) { j.confirmDelete = true } label: { Label("删除", systemImage: "trash") }
                        .disabled(total == 0)
                }
                .padding(10).background(RoundedRectangle(cornerRadius: 8).fill(Theme.red.opacity(0.07)))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.red.opacity(0.4)))
            }
        }
        .padding(14).panel()
        .onAppear { if j.delValue.isEmpty { j.delValue = j.defaultDelValue() } }
        .alert("确认删除？", isPresented: $j.confirmDelete) {
            Button("删除", role: .destructive) { Task { await j.doDelete() } }
            Button("取消", role: .cancel) {}
        } message: {
            Text("将永久删除 \(j.delPreview["from"].str) ~ \(j.delPreview["to"].str) 的所选数据，无法恢复。")
        }
    }
    var placeholder: String { ["day": "2026-11-25", "week": "该周任意一天", "month": "2026-11", "year": "2026", "before": "2026-10-25"][j.delUnit.rawValue]! }
    var hint: String {
        switch j.delUnit {
        case .day: return "输入日期 YYYY-MM-DD，删除这一天"
        case .week: return "输入该周任意一天，删除周一到周日"
        case .month: return "输入 YYYY-MM，删除整月"
        case .year: return "输入 YYYY，删除整年"
        case .before: return "删除这一天之前的全部数据（例如保留最近一个月）"
        }
    }
}


/// 当天的个股研判记录（每次研判自动存入数据库）
struct AnalysesList: View {
    @EnvironmentObject var s: Store
    let items: [JV]
    var fill: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("个股研判记录 · \(items.count) 次").font(.system(size: 11)).foregroundColor(Theme.dim)
            HStack(spacing: 0) {
                Text("").frame(width: 22)
                Text("时间").frame(width: 50, alignment: .leading)
                Text("股票").frame(width: 170, alignment: .leading)
                Text("价格").frame(width: 70, alignment: .trailing)
                Text("涨跌").frame(width: 64, alignment: .trailing)
                Text("评级").frame(width: 96, alignment: .leading).padding(.leading, 12)
                Text("综合分").frame(width: 50, alignment: .trailing)
                Text("买入区间").frame(width: 120, alignment: .trailing)
                Text("止损").frame(width: 70, alignment: .trailing)
                Text("风险回报").frame(width: 66, alignment: .trailing)
                Spacer(minLength: 0)
            }
            .font(.system(size: 10.5)).foregroundColor(Theme.dim)
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(items, id: \.self) { a in
                        HStack(spacing: 0) {
                            FavStar(source: "stock", market: a["market"].str, date: a["date"].str, code: a["code"].str, name: a["name"].str,
                                    method: "个股研判", price: a["price"].num, size: 12).frame(width: 22, alignment: .leading)
                            Text(String(a["created"].str.dropFirst(11).prefix(5))).font(monoF(11.5)).frame(width: 50, alignment: .leading)
                            Button { s.openStock(a["code"].str) } label: {
                                HStack(spacing: 5) {
                                    Text(a["name"].str).font(.system(size: 12.5, weight: .semibold)).lineLimit(1)
                                    Text("\(a["code"].str) · \(a["market"].str)").font(monoF(10)).foregroundColor(Theme.dim)
                                }
                            }
                            .buttonStyle(.plain).frame(width: 170, alignment: .leading).help("打开个股研判")
                            Text(a["price"].num.map { String(format: "%.2f", $0) } ?? "—").font(monoF(11.5)).frame(width: 70, alignment: .trailing)
                            Text(pctText(a["chg"])).font(monoF(11.5)).foregroundColor(Theme.up(a["chg"].num ?? 0)).frame(width: 64, alignment: .trailing)
                            Text(a["rating"].str).font(.system(size: 12, weight: .semibold)).lineLimit(1).frame(width: 96, alignment: .leading).padding(.leading, 12)
                            Text(a["score"].num.map { String(Int($0)) } ?? "—").font(monoF(11.5)).frame(width: 50, alignment: .trailing)
                            Text(a["buy_lo"].num.map { String(format: "%.2f–%.2f", $0, a["buy_hi"].num ?? 0) } ?? "—").font(monoF(11.5)).frame(width: 120, alignment: .trailing)
                            Text(a["stop"].num.map { String(format: "%.2f", $0) } ?? "—").font(monoF(11.5)).frame(width: 70, alignment: .trailing)
                            Text(a["rr"].num.map { String(format: "%.2f", $0) } ?? "—").font(monoF(11.5)).frame(width: 66, alignment: .trailing)
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 4).padding(.horizontal, 6)
                        .help(a["summary"].str)
                    }
                }
            }
            .frame(maxHeight: fill ? .infinity : 150)
        }
        .padding(.top, 6)
    }
}

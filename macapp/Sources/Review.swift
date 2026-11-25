import SwiftUI

// MARK: - 每日复盘页：外围 → 外围对 A 股的影响 → A 股大盘 → 资金 → 板块与原因 → 选股比对 → 汇总

struct ReviewPage: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        let r = j.review["data"]
        VStack(spacing: 10) {
            ReviewHeader()
            if r.isNull {
                VStack(spacing: 12) {
                    Spacer()
                    Text(j.reviewRunning ? "正在生成复盘（约 1 分钟）…" : "还没有复盘").font(.system(size: 16)).foregroundColor(Theme.dim)
                    if !j.reviewRunning { Button("生成今日复盘") { Task { await j.buildReview() } }.buttonStyle(.borderedProminent) }
                    Spacer()
                }
                .frame(maxWidth: .infinity).panel()
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(spacing: 10) {
                            ExternalCard(r: r).id(1)
                            ImpactCard(r: r).id(2)
                            AMarketCard(r: r).id(3)
                            FlowCard(r: r).id(4)
                            SectorCard(r: r).id(5)
                            PicksCompareCard(r: r).id(6)
                            SummaryCard(r: r).id(7)
                        }
                    }
                    .onChange(of: j.scrollTo) { _, v in if let v { proxy.scrollTo(v, anchor: .top) } }
                }
            }
        }
        .task { if j.review.isNull { await j.loadReview() } }
    }
}

struct ReviewHeader: View {
    @EnvironmentObject var j: JournalModel
    var body: some View {
        let r = j.review["data"]
        HStack(alignment: .center, spacing: 14) {
            Text("复").font(.system(size: 26, weight: .bold)).foregroundColor(Theme.red)
                .frame(width: 60, height: 60)
                .background(RoundedRectangle(cornerRadius: 14).fill(Theme.red.opacity(0.06)))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.red.opacity(0.85), lineWidth: 1.5))
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 10) {
                    Text("每日复盘").font(.system(size: 24, weight: .semibold))
                    if !r.isNull {
                        Pill(text: "\(r["date"].str) \(weekday(r["date"].str)) · \(r["kind"].str)", color: Theme.red)
                    }
                }
                Text(r.isNull ? "外围市场 · 成交量 · 资金流向 · 板块原因 · 选股比对" :
                        "生成于 \(r["generated"].str)（北京时间）· 用时 \(r["seconds"].int) 秒" + (r["errors"].arr.isEmpty ? "" : " · \(r["errors"].arr.count) 项数据取不到"))
                    .font(.system(size: 12)).foregroundColor(r["errors"].arr.isEmpty ? Theme.dim : Theme.yellow)
            }
            Spacer()
            if j.reviewRunning {
                ProgressView().controlSize(.small)
                Text(j.reviewLog.last ?? "正在抓取数据…").font(monoF(11)).foregroundColor(Theme.dim).lineLimit(1).frame(maxWidth: 300)
            }
            Picker("", selection: Binding(get: { j.reviewDate }, set: { d in j.reviewDate = d; Task { await j.loadReview(d) } })) {
                ForEach(Array(Set(j.reviewDates + [j.reviewDate])).filter { !$0.isEmpty }.sorted(by: >), id: \.self) { Text($0).tag($0) }
            }
            .labelsHidden().frame(width: 130).help("历史复盘")
            Button { Task { await j.buildReview() } } label: {
                Label(j.reviewRunning ? "生成中…" : "生成 / 更新今日复盘", systemImage: "doc.text.magnifyingglass")
            }
            .buttonStyle(.borderedProminent).tint(Theme.red.opacity(0.8)).disabled(j.reviewRunning)
        }
        .padding(14).panel()
    }
}

struct CardTitle: View {
    let n: String, title: String
    var sub: String = ""
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(n).font(monoF(12, .bold)).foregroundColor(Theme.bg).frame(width: 20, height: 20)
                .background(Circle().fill(Theme.red.opacity(0.85)))
            Text(title).font(.system(size: 16, weight: .bold))
            Text(sub).font(.system(size: 11.5)).foregroundColor(Theme.dim)
            Spacer()
        }
    }
}

struct QuoteList: View {
    let title: String
    let items: [JV]
    var showTime = false
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.dim)
            ForEach(items, id: \.self) { x in
                HStack {
                    Text(x["name"].str).font(.system(size: 12.5))
                    Spacer()
                    Text(x["price"].num.map { $0 >= 1000 ? String(format: "%.0f", $0) : String(format: "%.2f", $0) } ?? "—")
                        .font(monoF(12)).foregroundColor(Theme.dim)
                    Text(pctText(x["chg"])).font(monoF(12.5, .semibold)).foregroundColor(Theme.up(x["chg"].num ?? 0))
                        .frame(width: 70, alignment: .trailing)
                }
            }
        }
        .padding(12).frame(maxWidth: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 9).fill(Theme.panel2))
    }
}

struct ExternalCard: View {
    let r: JV
    var body: some View {
        let e = r["external"]
        VStack(alignment: .leading, spacing: 10) {
            CardTitle(n: "1", title: "外围市场", sub: "A 股开盘前：隔夜美股（\(e["us_date"].str) 收盘）、亚太、商品与汇率")
            HStack(alignment: .top, spacing: 10) {
                QuoteList(title: "隔夜美股", items: e["us"].arr)
                QuoteList(title: "港股 · 亚太 · A50", items: e["asia"].arr)
                QuoteList(title: "商品 · 汇率", items: e["commodity"].arr + e["fx"].arr)
            }
        }
        .padding(14).panel()
    }
}

struct ImpactCard: View {
    let r: JV
    var body: some View {
        let imps = r["impacts"].arr
        VStack(alignment: .leading, spacing: 8) {
            CardTitle(n: "2", title: "外围对 A 股的影响", sub: "预期方向 vs 当天相关板块实际涨跌（兑现 / 背离）")
            ForEach(imps, id: \.self) { i in
                let strong = i["strong"].bool
                let v = i["verdict"].str
                HStack(alignment: .top, spacing: 10) {
                    Text(i["factor"].str).font(monoF(12.5, .semibold)).foregroundColor(Theme.up(i["chg"].num ?? 0)).frame(width: 170, alignment: .leading)
                    Text(i["group"].str).font(.system(size: 12.5, weight: .semibold)).frame(width: 110, alignment: .leading)
                    Text(i["expect"].str).font(.system(size: 12, weight: .bold))
                        .foregroundColor(i["expect"].str == "利好" ? Theme.red : (i["expect"].str == "利空" ? Theme.green : Theme.faint))
                        .frame(width: 64, alignment: .leading)
                    VStack(alignment: .leading, spacing: 3) {
                        if let a = i["actual"].num {
                            HStack(spacing: 6) {
                                Text("相关板块平均 \(signed(a))").font(monoF(12)).foregroundColor(Theme.up(a))
                                if !v.isEmpty {
                                    Text(v).font(.system(size: 10.5, weight: .bold))
                                        .foregroundColor(v == "兑现" ? Theme.gold : (v == "背离" ? Theme.blue : Theme.dim))
                                        .padding(.horizontal, 6).padding(.vertical, 1).overlay(Capsule().stroke(Theme.line))
                                }
                            }
                        }
                        let secs = i["sectors"].arr
                        if !secs.isEmpty {
                            Text(secs.map { "\($0["name"].str) \(pctText($0["zdf"]))" }.joined(separator: "  "))
                                .font(.system(size: 11)).foregroundColor(Theme.dim).lineLimit(1)
                        }
                    }
                    Spacer()
                }
                .padding(.vertical, 5).padding(.horizontal, 8)
                .background(RoundedRectangle(cornerRadius: 6).fill(strong ? Theme.panel2 : Color.clear))
                .opacity(strong ? 1 : 0.6)
            }
        }
        .padding(14).panel()
    }
}

struct AMarketCard: View {
    let r: JV
    var body: some View {
        let t = r["turnover"], b = r["breadth"]
        VStack(alignment: .leading, spacing: 10) {
            CardTitle(n: "3", title: "A 股大盘", sub: "指数 · 成交额 · 涨跌家数 · 涨停跌停 · 连板（沪深 A 股，不含北交所 / ST）")
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 8), spacing: 8) {
                ForEach(r["indices"].arr, id: \.self) { x in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(x["name"].str).font(.system(size: 11.5)).foregroundColor(Theme.dim)
                        Text(x["price"].num.map { String(format: "%.2f", $0) } ?? "—").font(monoF(14, .semibold))
                        Text(pctText(x["chg"])).font(monoF(13, .bold)).foregroundColor(Theme.up(x["chg"].num ?? 0))
                    }
                    .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Theme.panel2))
                }
            }
            HStack(alignment: .top, spacing: 10) {
                // 成交额
                VStack(alignment: .leading, spacing: 8) {
                    Text("两市成交额").font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.dim)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(yi(t["total"].num)).font(monoF(24, .bold))
                        if let c = t["change"].num {
                            Text("\(c > 0 ? "放量" : "缩量") \(yi(abs(c))) (\(pctText(t["change_pct"], 1)))").font(monoF(12.5, .semibold))
                                .foregroundColor(c > 0 ? Theme.red : Theme.green)
                        }
                    }
                    Text("沪 \(yi(t["sh"].num)) · 深 \(yi(t["sz"].num)) · 5 日均 \(yi(t["avg5"].num))").font(.system(size: 11.5)).foregroundColor(Theme.dim)
                    let h = t["history"].arr
                    let mx = h.compactMap { $0["total"].num }.max() ?? 1
                    HStack(alignment: .bottom, spacing: 10) {
                        ForEach(h, id: \.self) { x in
                            VStack(spacing: 3) {
                                Text(String(format: "%.1f", (x["total"].num ?? 0) / 10000)).font(monoF(9.5)).foregroundColor(Theme.dim)
                                RoundedRectangle(cornerRadius: 3).fill(x == h.last ? Theme.blue : Theme.blue.opacity(0.35))
                                    .frame(width: 30, height: CGFloat((x["total"].num ?? 0) / mx) * 70)
                                Text(String(x["date"].str.suffix(5))).font(monoF(9.5)).foregroundColor(Theme.faint)
                            }
                        }
                    }
                    .frame(height: 100, alignment: .bottom)
                    Text("单位：万亿").font(.system(size: 9.5)).foregroundColor(Theme.faint)
                }
                .padding(12).frame(width: 300, alignment: .topLeading)
                .background(RoundedRectangle(cornerRadius: 9).fill(Theme.panel2))
                // 涨跌分布
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("涨跌分布").font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.dim)
                        Spacer()
                        Text("涨 \(b["up"].int)").font(monoF(12.5, .bold)).foregroundColor(Theme.red)
                        Text("平 \(b["flat"].int)").font(monoF(12)).foregroundColor(Theme.dim)
                        Text("跌 \(b["down"].int)").font(monoF(12.5, .bold)).foregroundColor(Theme.green)
                    }
                    let up = Double(b["up"].int), dn = Double(b["down"].int)
                    GeometryReader { g in
                        HStack(spacing: 0) {
                            Rectangle().fill(Theme.red).frame(width: g.size.width * up / max(1, up + dn))
                            Rectangle().fill(Theme.green)
                        }
                    }
                    .frame(height: 6).clipShape(Capsule())
                    let dist = b["dist"].arr
                    let mx = Double(dist.map { $0["n"].int }.max() ?? 1)
                    HStack(alignment: .bottom, spacing: 6) {
                        ForEach(Array(dist.enumerated()), id: \.offset) { i, x in
                            VStack(spacing: 3) {
                                Text("\(x["n"].int)").font(monoF(9.5)).foregroundColor(Theme.dim)
                                RoundedRectangle(cornerRadius: 3).fill(i < 4 ? Theme.red.opacity(0.8) : (i == 4 ? Theme.dim : Theme.green.opacity(0.8)))
                                    .frame(height: max(2, CGFloat(Double(x["n"].int) / max(1, mx)) * 70))
                                Text(x["label"].str).font(.system(size: 9)).foregroundColor(Theme.faint).lineLimit(1).minimumScaleFactor(0.7)
                            }
                            .frame(maxWidth: .infinity)
                        }
                    }
                    .frame(height: 100, alignment: .bottom)
                    Text("中位数 \(pctText(b["median"])) · 平均 \(pctText(b["mean"]))").font(.system(size: 11)).foregroundColor(Theme.dim)
                }
                .padding(12).frame(maxWidth: .infinity, alignment: .topLeading)
                .background(RoundedRectangle(cornerRadius: 9).fill(Theme.panel2))
                // 涨停
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 14) {
                        stat("涨停", "\(b["limit_up"].int)", Theme.red)
                        stat("跌停", "\(b["limit_down"].int)", Theme.green)
                        stat("炸板", "\(b["zhaban"].int)", Theme.yellow)
                        stat("炸板率", b["zhaban_rate"].num.map { String(format: "%.0f%%", $0) } ?? "—", Theme.yellow)
                    }
                    Text("连板梯队（最高 \(b["max_streak"].int) 板）").font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.dim).padding(.top, 4)
                    ForEach(b["ladder"].arr.prefix(5), id: \.self) { l in
                        HStack(alignment: .top, spacing: 8) {
                            Text("\(l["n"].int) 板").font(monoF(12, .bold)).foregroundColor(l["n"].int >= 3 ? Theme.gold : Theme.ink).frame(width: 36, alignment: .leading)
                            Text("\(l["count"].int) 只").font(monoF(11)).foregroundColor(Theme.dim).frame(width: 36, alignment: .leading)
                            Text(l["stocks"].arr.prefix(8).map { $0["name"].str }.joined(separator: "、"))
                                .font(.system(size: 11.5)).lineLimit(2).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(12).frame(width: 380, alignment: .topLeading)
                .background(RoundedRectangle(cornerRadius: 9).fill(Theme.panel2))
            }
        }
        .padding(14).panel()
    }
    func stat(_ t: String, _ v: String, _ c: Color) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(t).font(.system(size: 11)).foregroundColor(Theme.dim)
            Text(v).font(monoF(18, .bold)).foregroundColor(c)
        }
    }
}

struct FlowList: View {
    let title: String
    let items: [JV]
    var body: some View {
        let mx = items.compactMap { $0["flow"].num.map(abs) }.max() ?? 1
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.dim)
            ForEach(items.prefix(10), id: \.self) { x in
                let f = x["flow"].num ?? 0
                HStack(spacing: 6) {
                    Text(x["name"].str).font(.system(size: 12)).lineLimit(1).frame(width: 92, alignment: .leading)
                    Text(pctText(x["zdf"])).font(monoF(10.5)).foregroundColor(Theme.up(x["zdf"].num ?? 0)).frame(width: 52, alignment: .trailing)
                    GeometryReader { g in
                        RoundedRectangle(cornerRadius: 2).fill(f >= 0 ? Theme.red.opacity(0.75) : Theme.green.opacity(0.75))
                            .frame(width: max(2, g.size.width * abs(f) / mx))
                    }
                    .frame(height: 8)
                    Text(String(format: "%+.1f亿", f)).font(monoF(11, .semibold)).foregroundColor(Theme.up(f)).frame(width: 64, alignment: .trailing)
                }
            }
        }
        .padding(12).frame(maxWidth: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 9).fill(Theme.panel2))
    }
}

struct FlowCard: View {
    let r: JV
    var body: some View {
        let f = r["flow"]
        VStack(alignment: .leading, spacing: 10) {
            CardTitle(n: "4", title: "资金流向", sub: "主力净流入 = 超大单 + 大单（腾讯口径）；行业为申万一级")
            HStack(spacing: 10) {
                Kpi(title: "全市场主力净流入", value: String(format: "%+.0f 亿", f["main"].num ?? 0), sub: "今日", color: Theme.up(f["main"].num ?? 0))
                Kpi(title: "近 5 日累计", value: String(format: "%+.0f 亿", f["main5"].num ?? 0), sub: "主力", color: Theme.up(f["main5"].num ?? 0))
                Kpi(title: "近 20 日累计", value: String(format: "%+.0f 亿", f["main20"].num ?? 0), sub: "主力", color: Theme.up(f["main20"].num ?? 0))
                let ind = f["industries"].arr
                Kpi(title: "净流入行业", value: "\(ind.filter { ($0["flow"].num ?? 0) > 0 }.count) / \(ind.count)", sub: "申万一级")
                Spacer()
            }
            HStack(alignment: .top, spacing: 10) {
                FlowList(title: "行业 · 净流入前 10", items: f["in"].arr)
                FlowList(title: "行业 · 净流出前 10", items: f["out"].arr)
                FlowList(title: "概念 · 净流入前 10", items: f["concept_in"].arr)
                FlowList(title: "概念 · 净流出前 10", items: f["concept_out"].arr)
            }
        }
        .padding(14).panel()
    }
}

struct SectorBlock: View {
    let b: JV
    var body: some View {
        let z = b["zdf"].num ?? 0
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(b["name"].str).font(.system(size: 14, weight: .bold))
                Text(signed(z)).font(monoF(14, .bold)).foregroundColor(Theme.up(z))
                Spacer()
                Text(String(format: "%+.1f 亿", b["flow"].num ?? 0)).font(monoF(11.5)).foregroundColor(Theme.up(b["flow"].num ?? 0))
            }
            ForEach(b["reasons"].arr, id: \.self) { x in
                Text("· " + x.str).font(.system(size: 11.5)).foregroundColor(x.str.hasPrefix("外围") ? Theme.gold : Theme.ink.opacity(0.85))
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(b["news"].arr, id: \.self) { n in
                HStack(alignment: .top, spacing: 5) {
                    Text(n["time"].str).font(monoF(10)).foregroundColor(Theme.faint)
                    if let u = URL(string: n["url"].str), !n["url"].str.isEmpty {
                        Link(n["title"].str, destination: u).font(.system(size: 11)).foregroundColor(Theme.blue).lineLimit(2)
                    } else {
                        Text(n["title"].str).font(.system(size: 11)).foregroundColor(Theme.dim).lineLimit(2)
                    }
                }
            }
        }
        .padding(10).frame(maxWidth: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 8).fill(Theme.panel2))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.up(z).opacity(0.35)))
    }
}

struct SectorCard: View {
    let r: JV
    var body: some View {
        let s = r["sectors"]
        VStack(alignment: .leading, spacing: 10) {
            CardTitle(n: "5", title: "板块涨跌与主要原因", sub: "原因 = 资金 + 涨跌家数 + 龙头/成分股 + 外围联动 + 当天相关快讯（东方财富 7×24）")
            HStack(alignment: .top, spacing: 10) {
                col("行业领涨（申万二级）", s["top"].arr)
                col("行业领跌（申万二级）", s["bottom"].arr)
                col("概念领涨", s["concept_top"].arr)
                col("概念领跌", s["concept_bottom"].arr)
            }
        }
        .padding(14).panel()
    }
    func col(_ t: String, _ bs: [JV]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(t).font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.dim)
            ForEach(bs.prefix(5), id: \.self) { SectorBlock(b: $0) }
        }
        .frame(maxWidth: .infinity, alignment: .top)
    }
}

struct PicksCompareCard: View {
    let r: JV
    var body: some View {
        let y = r["yesterday"]
        let p = r["picks"]
        VStack(alignment: .leading, spacing: 10) {
            CardTitle(n: "6", title: "选股比对", sub: "上一交易日（\(y["date"].str)）选出的股票今天表现；今天的选股已存入数据库，明天自动比对")
            HStack(spacing: 10) {
                Kpi(title: "今日主力选股", value: "\(p["screener"].int)", color: Theme.yellow)
                Kpi(title: "今日盯盘信号", value: "\(p["monitor"].int)", color: Theme.green)
                Kpi(title: "已验证 / 命中", value: "\(p["validated"].int)", color: Theme.gold)
                Spacer()
            }
            let ms = y["methods"].arr.filter { $0["n1"].int > 0 }
            if ms.isEmpty {
                Text("上一交易日没有存入数据库的选股，或还没有比对结果").font(.system(size: 12)).foregroundColor(Theme.faint)
            } else {
                HStack(spacing: 0) {
                    Text("方法").frame(maxWidth: .infinity, alignment: .leading)
                    Text("条数").frame(width: 60, alignment: .trailing)
                    Text("T+1 平均").frame(width: 80, alignment: .trailing)
                    Text("胜率").frame(width: 60, alignment: .trailing)
                    Text("超额").frame(width: 80, alignment: .trailing)
                    Text("跑赢大盘").frame(width: 80, alignment: .trailing)
                }
                .font(.system(size: 11)).foregroundColor(Theme.dim)
                ForEach(ms, id: \.self) { m in
                    HStack(spacing: 0) {
                        HStack(spacing: 5) {
                            Text(m["source"].str == "screener" ? "选股" : (m["market"].str == "us" ? "盯盘·美" : "盯盘")).font(.system(size: 10, weight: .bold)).foregroundColor(Theme.faint)
                            Text(m["method"].str).font(.system(size: 12.5, weight: .semibold))
                            Text(m["tier"].str).font(.system(size: 10)).foregroundColor(Theme.dim)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        Text("\(m["n1"].int)").font(monoF(12)).frame(width: 60, alignment: .trailing)
                        Text(pctText(m["r1"])).font(monoF(12, .semibold)).foregroundColor(Theme.up(m["r1"].num ?? 0)).frame(width: 80, alignment: .trailing)
                        Text(m["win1"].num.map { String(format: "%.0f%%", $0) } ?? "—").font(monoF(12)).frame(width: 60, alignment: .trailing)
                        Text(pctText(m["ex1"])).font(monoF(12)).foregroundColor(Theme.up(m["ex1"].num ?? 0)).frame(width: 80, alignment: .trailing)
                        Text(m["beat1"].num.map { String(format: "%.0f%%", $0) } ?? "—").font(monoF(12)).frame(width: 80, alignment: .trailing)
                    }
                }
            }
        }
        .padding(14).panel()
    }
}

struct SummaryCard: View {
    let r: JV
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            CardTitle(n: "7", title: "汇总与明日要点", sub: "由以上数据按规则生成，每个数字都可在上面找到出处")
            Text(r["summary"].str).font(.system(size: 13)).lineSpacing(5).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading).fixedSize(horizontal: false, vertical: true)
            if !r["outlook"].arr.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    Text("明日要点").font(.system(size: 12, weight: .semibold)).foregroundColor(Theme.gold)
                    ForEach(r["outlook"].arr, id: \.self) { Text("· " + $0.str).font(.system(size: 12.5)).fixedSize(horizontal: false, vertical: true) }
                }
                .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8).fill(Theme.gold.opacity(0.07)))
            }
            if !r["errors"].arr.isEmpty {
                Text("取不到的数据：" + r["errors"].arr.map { $0.str }.joined(separator: "；")).font(.system(size: 11)).foregroundColor(Theme.yellow)
            }
        }
        .padding(14).panel()
    }
}

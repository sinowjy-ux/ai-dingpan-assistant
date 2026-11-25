import SwiftUI

enum Page: Hashable { case dashboard, review, monitor, screener, stock }

// MARK: - 命中榜：纪律分 ≥ 60、未被剔除的信号单独醒目显示

struct HitBoard: View {
    @EnvironmentObject var s: Store
    var body: some View {
        let hits = Array(s.passed.reversed())
        let a = hits.filter { $0.grade == "A" }.count
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("★").font(.system(size: 18, weight: .bold)).foregroundColor(Theme.gold)
                Text("命中 · 纪律通过").font(.system(size: 16, weight: .bold)).foregroundColor(Theme.gold)
                Text("\(hits.count)").font(monoF(22, .bold)).foregroundColor(Theme.gold).contentTransition(.numericText())
                Spacer()
                Text("A 可执行 \(a) · B 观察 \(hits.count - a) · 共振 \(s.resonance.count)")
                    .font(.system(size: 11)).foregroundColor(Theme.dim)
            }
            Text("纪律分 ≥ 60 才算命中；被剔除的在下方“监控流水”里").font(.system(size: 10.5)).foregroundColor(Theme.faint)
            if hits.isEmpty {
                Spacer()
                VStack(spacing: 6) {
                    Text("☆").font(.system(size: 28)).foregroundColor(Theme.gold.opacity(0.4))
                    Text("还没有命中").foregroundColor(Theme.dim)
                }
                .frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing: 7) { ForEach(hits) { HitRow(sig: $0) } }
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(LinearGradient(colors: [Theme.gold.opacity(0.10), Theme.panel], startPoint: .top, endPoint: .center))
        )
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.gold.opacity(hits.isEmpty ? 0.35 : 0.8), lineWidth: 1.5))
        .fxShadow(color: Theme.gold.opacity(hits.isEmpty ? 0 : 0.25), radius: 12)
    }
}

struct HitRow: View {
    @EnvironmentObject var s: Store
    let sig: Signal
    var body: some View {
        let c = s.color(sig.strategy)
        let sel = s.selected?.id == sig.id
        let fresh = s.newHitIDs.contains(sig.id)
        let isA = sig.grade == "A"
        HStack(spacing: 0) {
            Rectangle().fill(c).frame(width: 4)
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(sig.time).font(monoF(12, .semibold))
                    if sig.backfill == true { Text("补算").font(.system(size: 9)).foregroundColor(Theme.dim) }
                }
                .frame(width: 44, alignment: .leading)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(sig.name).font(.system(size: 15, weight: .bold)).lineLimit(1)
                        Text(sig.code).font(monoF(10)).foregroundColor(Theme.dim)
                        if s.isResonance(sig.code) {
                            Text("共振").font(.system(size: 9.5, weight: .bold)).foregroundColor(Theme.bg)
                                .padding(.horizontal, 5).padding(.vertical, 1)
                                .background(Capsule().fill(Theme.green))
                        }
                    }
                    HStack(spacing: 6) {
                        Text(sig.strategy_name).font(.system(size: 11, weight: .semibold)).foregroundColor(c)
                        Text("量比 \(String(format: "%.1f", sig.lb)) · 涨 \(signed(sig.chg, 1)) · 止损 \(String(format: "%.2f", sig.stop))")
                            .font(.system(size: 10.5)).foregroundColor(Theme.ink.opacity(0.7)).lineLimit(1)
                    }
                }
                Spacer(minLength: 4)
                FavStar(source: "monitor", market: s.market, date: s.sigDate, code: sig.code, name: sig.name,
                        method: sig.strategy_name, price: sig.price, size: 14)
                VStack(alignment: .trailing, spacing: 3) {
                    Text("\(sig.score)").font(monoF(20, .bold)).foregroundColor(isA ? Theme.gold : Theme.green)
                    Text(isA ? "A 可执行" : "B 观察").font(.system(size: 10, weight: .bold))
                        .foregroundColor(isA ? Theme.bg : Theme.green)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Capsule().fill(isA ? Theme.gold : Color.clear))
                        .overlay(Capsule().stroke(isA ? Color.clear : Theme.green, lineWidth: 1))
                    if s.finished, let a = sig.after {
                        Text("收 \(signed(a.close, 1))").font(monoF(9.5)).foregroundColor(Theme.up(a.close))
                    }
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 8)
        }
        .background(
            RoundedRectangle(cornerRadius: 9).fill(
                LinearGradient(colors: [c.opacity(fresh ? 0.38 : (sel ? 0.24 : 0.15)), Theme.panel2.opacity(0.9)],
                               startPoint: .leading, endPoint: .trailing))
        )
        .clipShape(RoundedRectangle(cornerRadius: 9))
        .overlay(RoundedRectangle(cornerRadius: 9).stroke(sel || fresh ? c : c.opacity(0.35), lineWidth: sel || fresh ? 1.5 : 1))
        .fxShadow(color: fresh ? c.opacity(0.6) : .clear, radius: 8)
        .scaleEffect(fresh ? 1.01 : 1)
        .animation(.easeOut(duration: 0.4), value: fresh)
        .contentShape(Rectangle())
        .onTapGesture { s.selectedID = sig.id }
    }
}

// MARK: - 监控流水：所有信号（含被剔除的），弱化显示

struct StreamPanel: View {
    @EnvironmentObject var s: Store
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "监控流水 · 全部 \(s.shown.count)", trailing: "纪律剔除 \(s.cut)", trailingColor: Theme.red.opacity(0.8))
            if s.shown.isEmpty {
                Spacer()
                Text("还没有信号").font(.system(size: 12)).foregroundColor(Theme.faint).frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing: 2) {
                        ForEach(s.shown.reversed()) { sig in
                            let hit = sig.grade != "C"
                            HStack(spacing: 8) {
                                Text(sig.time).font(monoF(11)).foregroundColor(Theme.faint)
                                Text(hit ? "★" : "✕").font(.system(size: 11, weight: .bold))
                                    .foregroundColor(hit ? Theme.gold : Theme.faint).frame(width: 12)
                                Text(sig.name).font(.system(size: 12, weight: hit ? .semibold : .regular))
                                    .foregroundColor(hit ? Theme.ink : Theme.dim).strikethrough(!hit, color: Theme.faint).lineLimit(1)
                                Text(sig.strategy_name).font(.system(size: 11)).foregroundColor(hit ? s.color(sig.strategy) : Theme.faint).lineLimit(1)
                                Spacer(minLength: 2)
                                Text("\(sig.score)").font(monoF(11.5, .semibold)).foregroundColor(hit ? Theme.grade(sig.grade) : Theme.faint)
                            }
                            .padding(.horizontal, 6).padding(.vertical, 3)
                            .background(RoundedRectangle(cornerRadius: 5).fill(hit ? Theme.gold.opacity(0.06) : Color.clear))
                            .contentShape(Rectangle())
                            .onTapGesture { s.selectedID = sig.id }
                        }
                    }
                }
            }
        }
        .padding(12).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).panel()
    }
}

// MARK: - 新命中弹出提示

struct HitToast: View {
    @EnvironmentObject var s: Store
    let sig: Signal
    var body: some View {
        let c = s.color(sig.strategy)
        HStack(spacing: 12) {
            Text("★").font(.system(size: 22, weight: .bold)).foregroundColor(Theme.gold)
            VStack(alignment: .leading, spacing: 2) {
                Text("新命中 · \(sig.time)").font(.system(size: 11, weight: .bold)).foregroundColor(Theme.gold)
                HStack(spacing: 8) {
                    Text(sig.name).font(.system(size: 17, weight: .bold))
                    Text(sig.strategy_name).font(.system(size: 12, weight: .semibold)).foregroundColor(c)
                }
            }
            Text("\(sig.score) 分 · \(sig.grade == "A" ? "A 可执行" : "B 观察")").font(monoF(14, .bold))
                .foregroundColor(sig.grade == "A" ? Theme.gold : Theme.green)
        }
        .padding(.horizontal, 18).padding(.vertical, 10)
        .background(RoundedRectangle(cornerRadius: 14).fill(Theme.panel2.opacity(0.97)))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.gold, lineWidth: 1.5))
        .fxShadow(color: Theme.gold.opacity(0.45), radius: 18)
        .onTapGesture { s.selectedID = sig.id }
    }
}

// MARK: - 数据集未下载

struct DatasetPrompt: View {
    @EnvironmentObject var s: Store
    var body: some View {
        let d = s.dataset
        ZStack {
            Color.black.opacity(0.55).ignoresSafeArea()
            VStack(spacing: 14) {
                Text("\(s.marketName) · \(s.sizeLabel)").font(.system(size: 22, weight: .bold))
                if d?.building == true {
                    ProgressView().controlSize(.small)
                    Text("正在下载近 5 个交易日的分时…").foregroundColor(Theme.dim)
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(d?.log ?? [], id: \.self) { Text($0).font(monoF(11)).foregroundColor(Theme.dim) }
                    }
                } else {
                    Text("这个组合还没有下载数据").foregroundColor(Theme.dim)
                    Text("下载近 5 个交易日的分时\(s.market == "us" ? "和日K" : "")，约 \(d?.est_min ?? 3) 分钟，在后台进行。\n下载期间可以切回其它组合继续用。")
                        .font(.system(size: 12)).foregroundColor(Theme.faint).multilineTextAlignment(.center)
                    Button { Task { await s.download() } } label: {
                        Label("开始下载", systemImage: "arrow.down.circle.fill").frame(minWidth: 120)
                    }
                    .buttonStyle(.borderedProminent).tint(Theme.green.opacity(0.85)).controlSize(.large)
                }
            }
            .padding(28)
            .background(RoundedRectangle(cornerRadius: 16).fill(Theme.panel))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.line))
        }
    }
}

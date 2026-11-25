import SwiftUI
import WebKit

// MARK: - 个股研判：内嵌与 Windows 版同一个研判页面（后台的 /?embed=1），两边功能和计算结果完全一致

struct StockWebView: NSViewRepresentable {
    let url: URL
    func makeCoordinator() -> Coord { Coord() }
    final class Coord { var loaded: URL? }

    func makeNSView(context: Context) -> WKWebView {
        let w = WKWebView(frame: .zero)
        w.setValue(false, forKey: "drawsBackground")      // 透明底，跟随 App 背景色
        w.allowsMagnification = true
        context.coordinator.loaded = url
        w.load(URLRequest(url: url))
        return w
    }

    func updateNSView(_ w: WKWebView, context: Context) {
        if context.coordinator.loaded != url {           // 换股票或换界面颜色时重新打开
            context.coordinator.loaded = url
            w.load(URLRequest(url: url))
        }
    }
}

struct StockPage: View {
    @EnvironmentObject var s: Store
    var body: some View {
        StockWebView(url: s.stockURL)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.line))
    }
}

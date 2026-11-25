import AppKit

// 用法：make_icon <像素> <输出.png>  —— 深色圆角方块 + 绿色 ">_" + 一条上涨的信号曲线
let a = CommandLine.arguments
let n = CGFloat(Double(a[1]) ?? 1024)
let out = a[2]
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(n), pixelsHigh: Int(n), bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let inset = n * 0.09
let r = NSRect(x: inset, y: inset, width: n - 2 * inset, height: n - 2 * inset)
let bg = NSBezierPath(roundedRect: r, xRadius: n * 0.2, yRadius: n * 0.2)
NSGradient(starting: NSColor(red: 0.07, green: 0.10, blue: 0.14, alpha: 1), ending: NSColor(red: 0.03, green: 0.05, blue: 0.07, alpha: 1))!
    .draw(in: bg, angle: -90)
let green = NSColor(red: 0.24, green: 0.77, blue: 0.54, alpha: 1)
green.withAlphaComponent(0.85).setStroke()
bg.lineWidth = max(1, n * 0.012)
bg.stroke()
// 信号曲线（阶梯上涨）
let curve = NSBezierPath()
let pts: [(CGFloat, CGFloat)] = [(0.22, 0.30), (0.36, 0.30), (0.36, 0.36), (0.50, 0.36), (0.50, 0.44), (0.62, 0.44), (0.62, 0.50), (0.78, 0.62)]
curve.move(to: NSPoint(x: n * pts[0].0, y: n * pts[0].1))
for p in pts.dropFirst() { curve.line(to: NSPoint(x: n * p.0, y: n * p.1)) }
curve.lineWidth = max(1, n * 0.022)
curve.lineJoinStyle = .round
green.withAlphaComponent(0.55).setStroke()
curve.stroke()
let dot = NSBezierPath(ovalIn: NSRect(x: n * 0.78 - n * 0.03, y: n * 0.62 - n * 0.03, width: n * 0.06, height: n * 0.06))
NSColor.white.setFill(); dot.fill()
// ">_"
let font = NSFont.monospacedSystemFont(ofSize: n * 0.30, weight: .bold)
let s = NSAttributedString(string: ">_", attributes: [.font: font, .foregroundColor: green])
let sz = s.size()
s.draw(at: NSPoint(x: (n - sz.width) / 2, y: n * 0.50))
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))

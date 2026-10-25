import AppKit
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
for size in [16,32,64,128,256,512,1024] {
    // Render exact pixel dimensions, independent of the display's Retina scale.
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.cgContext.clear(CGRect(x: 0, y: 0, width: size, height: size))
    let s = CGFloat(size)
    NSColor.white.setFill()
    NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: s, height: s), xRadius: s*0.22, yRadius: s*0.22).fill()
    // White background and the original green orbital mark, without lettering.
    let green = NSColor(calibratedRed: 0.18, green: 0.40, blue: 0.33, alpha: 1)
    green.setStroke()
    let circle = NSBezierPath(ovalIn: NSRect(x: s*0.18, y: s*0.20, width: s*0.53, height: s*0.53))
    circle.lineWidth = max(1.2, s*0.026);circle.stroke()
    let orbit = NSBezierPath(ovalIn: NSRect(x: s*0.52, y: s*0.54, width: s*0.29, height: s*0.29))
    NSColor.white.setFill();orbit.fill()
    green.setStroke();orbit.lineWidth=max(1,s*0.018);orbit.stroke()
    green.setFill()
    NSBezierPath(ovalIn: NSRect(x:s*0.48,y:s*0.44,width:s*0.065,height:s*0.065)).fill()
    NSGraphicsContext.restoreGraphicsState()
    let png = bitmap.representation(using: .png, properties: [:])!
    let name = size == 1024 ? "icon_512x512@2x.png" : "icon_\(size)x\(size).png"
    try png.write(to:folder.appendingPathComponent(name))
    if size >= 32 && size <= 512 {
        try png.write(to:folder.appendingPathComponent("icon_\(size/2)x\(size/2)@2x.png"))
    }
}

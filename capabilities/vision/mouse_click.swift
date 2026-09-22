import Foundation
import CoreGraphics

// Native macOS CoreGraphics Mouse Controller
// Usage: max-mouse-click <x> <y> [click_type: click|double|right]

guard CommandLine.arguments.count >= 3 else {
    fputs("Usage: max-mouse-click <x> <y> [click|double|right]\n", stderr)
    exit(1)
}

guard let x = Double(CommandLine.arguments[1]),
      let y = Double(CommandLine.arguments[2]),
      x >= 0, y >= 0 else {
    fputs("Error: Invalid screen coordinates (must be non-negative numbers)\n", stderr)
    exit(1)
}

let clickType = CommandLine.arguments.count >= 4 ? CommandLine.arguments[3].lowercased() : "click"
let point = CGPoint(x: x, y: y)

// Move cursor to target point
CGWarpMouseCursorPosition(point)
Thread.sleep(forTimeInterval: 0.05)

if clickType == "right" {
    let down = CGEvent(mouseEventSource: nil, mouseType: .rightMouseDown, mouseCursorPosition: point, mouseButton: .right)
    let up = CGEvent(mouseEventSource: nil, mouseType: .rightMouseUp, mouseCursorPosition: point, mouseButton: .right)
    down?.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.05)
    up?.post(tap: .cghidEventTap)
} else if clickType == "double" {
    let down1 = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
    let up1 = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
    down1?.setIntegerValueField(.mouseEventClickState, value: 1)
    up1?.setIntegerValueField(.mouseEventClickState, value: 1)
    down1?.post(tap: .cghidEventTap)
    up1?.post(tap: .cghidEventTap)

    Thread.sleep(forTimeInterval: 0.08)

    let down2 = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
    let up2 = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
    down2?.setIntegerValueField(.mouseEventClickState, value: 2)
    up2?.setIntegerValueField(.mouseEventClickState, value: 2)
    down2?.post(tap: .cghidEventTap)
    up2?.post(tap: .cghidEventTap)
} else {
    // Single left click
    let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
    let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
    down?.setIntegerValueField(.mouseEventClickState, value: 1)
    up?.setIntegerValueField(.mouseEventClickState, value: 1)
    down?.post(tap: .cghidEventTap)
    Thread.sleep(forTimeInterval: 0.05)
    up?.post(tap: .cghidEventTap)
}

print("CLICK_SUCCESS:\(x):\(y):\(clickType)")
exit(0)

import Foundation
import Cocoa
import ApplicationServices

// Native macOS Accessibility Tree Extractor for MAX 2.0
// High-performance, zero-hallucination recursive accessibility inspection.

struct ExtractionConfig {
    var pid: pid_t? = nil
    var appName: String? = nil
    var maxDepth: Int = 6
    var maxElements: Int = 100
    var timeoutMs: Double = 1500.0
    var maxChildrenPerNode: Int = 50
    var activeWindowOnly: Bool = false
}

func parseArguments() -> ExtractionConfig {
    var config = ExtractionConfig()
    let args = CommandLine.arguments
    var i = 1
    while i < args.count {
        let arg = args[i]
        if arg == "--pid", i + 1 < args.count {
            config.pid = pid_t(args[i + 1])
            i += 1
        } else if arg == "--app", i + 1 < args.count {
            config.appName = args[i + 1]
            i += 1
        } else if arg == "--max-depth", i + 1 < args.count {
            if let v = Int(args[i + 1]), v > 0 { config.maxDepth = v }
            i += 1
        } else if arg == "--max-elements", i + 1 < args.count {
            if let v = Int(args[i + 1]), v > 0 { config.maxElements = v }
            i += 1
        } else if arg == "--timeout-ms", i + 1 < args.count {
            if let v = Double(args[i + 1]), v > 0 { config.timeoutMs = v }
            i += 1
        } else if arg == "--max-children", i + 1 < args.count {
            if let v = Int(args[i + 1]), v > 0 { config.maxChildrenPerNode = v }
            i += 1
        } else if arg == "--active-window-only" {
            config.activeWindowOnly = true
        }
        i += 1
    }
    return config
}

func emitJSONAndExit(_ dict: [String: Any]) -> Never {
    if let data = try? JSONSerialization.data(withJSONObject: dict, options: [.fragmentsAllowed]),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    } else {
        print("{\"status\":\"ERROR\",\"error\":\"Failed to serialize JSON output\"}")
    }
    exit(0)
}

let startTime = CFAbsoluteTimeGetCurrent()
let config = parseArguments()

// 1. Accessibility Trust Check
let isTrusted = AXIsProcessTrusted()
if !isTrusted {
    emitJSONAndExit([
        "status": "ACCESSIBILITY_DENIED",
        "error": "macOS Accessibility permission is not granted. Please enable MAX / terminal in System Settings -> Privacy & Security -> Accessibility.",
        "stats": ["duration_ms": (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0]
    ])
}

// 2. Resolve Target Application
var targetApp: NSRunningApplication? = nil

if let p = config.pid {
    targetApp = NSRunningApplication(processIdentifier: p)
} else if let name = config.appName, !name.trimmingCharacters(in: .whitespaces).isEmpty {
    let lowerName = name.lowercased()
    let apps = NSWorkspace.shared.runningApplications
    targetApp = apps.first { app in
        let appName = (app.localizedName ?? "").lowercased()
        let bundleId = (app.bundleIdentifier ?? "").lowercased()
        return appName == lowerName || appName.contains(lowerName) || bundleId == lowerName || bundleId.contains(lowerName)
    }
} else {
    targetApp = NSWorkspace.shared.frontmostApplication
}

guard let app = targetApp else {
    emitJSONAndExit([
        "status": "ACCESSIBILITY_UNAVAILABLE",
        "error": "Target application could not be resolved or is not running.",
        "stats": ["duration_ms": (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0]
    ])
}

let pid = app.processIdentifier
let appName = app.localizedName ?? "Unknown"
let axApp = AXUIElementCreateApplication(pid)

// Set messaging timeout on AXUIElement API calls to avoid hanging on unresponsive apps
AXUIElementSetMessagingTimeout(axApp, Float(min(config.timeoutMs / 1000.0, 1.0)))

// Helper for extracting string attribute
func getStringAttribute(_ el: AXUIElement, _ attr: CFString) -> String? {
    var ref: CFTypeRef?
    let res = AXUIElementCopyAttributeValue(el, attr, &ref)
    if res == .success, let val = ref {
        if let s = val as? String {
            let trimmed = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return (trimmed.isEmpty || trimmed == "missing value") ? nil : trimmed
        } else if let num = val as? NSNumber {
            return num.stringValue
        } else if CFGetTypeID(val) == CFStringGetTypeID() {
            let s = val as! String
            let trimmed = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return (trimmed.isEmpty || trimmed == "missing value") ? nil : trimmed
        }
    }
    return nil
}

// Helper for extracting boolean attribute
func getBoolAttribute(_ el: AXUIElement, _ attr: CFString) -> Bool? {
    var ref: CFTypeRef?
    let res = AXUIElementCopyAttributeValue(el, attr, &ref)
    if res == .success, let val = ref {
        if let b = val as? Bool {
            return b
        } else if let n = val as? NSNumber {
            return n.boolValue
        }
    }
    return nil
}

// Helper for bounds (strictly real CoreGraphics bounds)
func getBounds(_ el: AXUIElement) -> [String: Double]? {
    var posRef: CFTypeRef?
    var sizeRef: CFTypeRef?
    let resPos = AXUIElementCopyAttributeValue(el, kAXPositionAttribute as CFString, &posRef)
    let resSize = AXUIElementCopyAttributeValue(el, kAXSizeAttribute as CFString, &sizeRef)
    if resPos == .success, resSize == .success,
       let pVal = posRef, let sVal = sizeRef,
       CFGetTypeID(pVal) == AXValueGetTypeID(),
       CFGetTypeID(sVal) == AXValueGetTypeID() {
        var pt = CGPoint.zero
        var sz = CGSize.zero
        if AXValueGetValue(pVal as! AXValue, .cgPoint, &pt),
           AXValueGetValue(sVal as! AXValue, .cgSize, &sz) {
            if sz.width > 0 && sz.height > 0 {
                return [
                    "x": Double(pt.x),
                    "y": Double(pt.y),
                    "width": Double(sz.width),
                    "height": Double(sz.height)
                ]
            }
        }
    }
    return nil
}

// Helper for actions (strictly real exposed AX action names)
func getActions(_ el: AXUIElement) -> [String] {
    var actionsRef: CFArray?
    if AXUIElementCopyActionNames(el, &actionsRef) == .success,
       let acts = actionsRef as? [String] {
        return acts
    }
    return []
}

// 3. Inspect Windows
var windowsData: [[String: Any]] = []
var activeWindowDict: [String: Any]? = nil
var orderedWindowElements: [AXUIElement] = []

var windowsRef: CFTypeRef?
if AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString, &windowsRef) == .success,
   let winArray = windowsRef as? [AXUIElement] {
    
    // Check focused window
    var focusedWinRef: CFTypeRef?
    var focusedWinElement: AXUIElement? = nil
    if AXUIElementCopyAttributeValue(axApp, kAXFocusedWindowAttribute as CFString, &focusedWinRef) == .success,
       let fw = focusedWinRef {
        focusedWinElement = (fw as! AXUIElement)
    }

    var activeIndex: Int = 0
    for (idx, win) in winArray.enumerated() {
        let isFocused = (focusedWinElement != nil && CFEqual(win, focusedWinElement!)) || (getBoolAttribute(win, kAXFocusedAttribute as CFString) ?? false)
        if isFocused {
            activeIndex = idx
            break
        }
    }

    for (idx, win) in winArray.enumerated() {
        let title = getStringAttribute(win, kAXTitleAttribute as CFString) ?? ""
        let role = getStringAttribute(win, kAXRoleAttribute as CFString) ?? "AXWindow"
        let subrole = getStringAttribute(win, kAXSubroleAttribute as CFString)
        let isFocused = (idx == activeIndex)
        let isMinimized = getBoolAttribute(win, kAXMinimizedAttribute as CFString) ?? false
        let isModal = getBoolAttribute(win, kAXModalAttribute as CFString) ?? false
        let bounds = getBounds(win)
        
        var winDict: [String: Any] = [
            "title": title,
            "role": role,
            "is_focused": isFocused,
            "is_minimized": isMinimized,
            "is_modal": isModal,
            "pid": Int(pid)
        ]
        if let s = subrole { winDict["subrole"] = s }
        if let b = bounds { winDict["bounds"] = b }
        
        windowsData.append(winDict)
    }

    if !winArray.isEmpty {
        activeWindowDict = windowsData[activeIndex]
        orderedWindowElements.append(winArray[activeIndex])
        if !config.activeWindowOnly {
            for (idx, win) in winArray.enumerated() {
                if idx != activeIndex {
                    orderedWindowElements.append(win)
                }
            }
        }
    }
}

// 4. Query Focused UI Element
var focusedUIDict: [String: Any]? = nil
var focusedElementRef: CFTypeRef?
var actualFocusedAXElement: AXUIElement? = nil
if AXUIElementCopyAttributeValue(axApp, kAXFocusedUIElementAttribute as CFString, &focusedElementRef) == .success,
   let fe = focusedElementRef {
    let fel = (fe as! AXUIElement)
    actualFocusedAXElement = fel
    let fRole = getStringAttribute(fel, kAXRoleAttribute as CFString) ?? "AXUnknown"
    var fDict: [String: Any] = [
        "role": fRole,
        "is_focused": true
    ]
    if let en = getBoolAttribute(fel, kAXEnabledAttribute as CFString) { fDict["is_enabled"] = en }
    if let t = getStringAttribute(fel, kAXTitleAttribute as CFString) { fDict["title"] = t }
    if let v = getStringAttribute(fel, kAXValueAttribute as CFString) { fDict["value"] = v }
    if let d = getStringAttribute(fel, kAXDescriptionAttribute as CFString) { fDict["description"] = d }
    if let sub = getStringAttribute(fel, kAXSubroleAttribute as CFString) { fDict["subrole"] = sub }
    if let ident = getStringAttribute(fel, kAXIdentifierAttribute as CFString) { fDict["identifier"] = ident }
    if let b = getBounds(fel) { fDict["bounds"] = b }
    let acts = getActions(fel)
    if !acts.isEmpty { fDict["actions"] = acts }
    focusedUIDict = fDict
}

// 5. Recursive Traversal State
var totalVisited = 0
var interactiveNodes: [[String: Any]] = []
var maxDepthReached = 0
var nodesByDepth: [String: Int] = [:]
var truncatedByMaxElements = false
var truncatedByMaxChildren = false
var timedOut = false
var isTruncated = false

let interactiveRoles: Set<String> = [
    "AXButton", "AXTextField", "AXTextArea", "AXSearchField",
    "AXPopUpButton", "AXCheckBox", "AXRadioButton", "AXTabGroup",
    "AXLink", "AXMenuItem", "AXMenuButton", "AXRow", "AXSlider",
    "AXColorWell", "AXComboBox", "AXStaticText", "AXImage"
]

func traverse(
    _ el: AXUIElement,
    currentPath: String,
    parentPath: String?,
    depth: Int
) -> [String: Any]? {
    let now = CFAbsoluteTimeGetCurrent()
    if (now - startTime) * 1000.0 >= config.timeoutMs {
        timedOut = true
        isTruncated = true
        return nil
    }
    
    if totalVisited >= config.maxElements {
        truncatedByMaxElements = true
        isTruncated = true
        return nil
    }
    
    totalVisited += 1
    if depth > maxDepthReached {
        maxDepthReached = depth
    }
    nodesByDepth["\(depth)", default: 0] += 1
    
    let role = getStringAttribute(el, kAXRoleAttribute as CFString) ?? "AXUnknown"
    let subrole = getStringAttribute(el, kAXSubroleAttribute as CFString)
    let title = getStringAttribute(el, kAXTitleAttribute as CFString) ?? ""
    let value = getStringAttribute(el, kAXValueAttribute as CFString)
    let desc = getStringAttribute(el, kAXDescriptionAttribute as CFString)
    let identifier = getStringAttribute(el, kAXIdentifierAttribute as CFString)
    let enabled = getBoolAttribute(el, kAXEnabledAttribute as CFString)
    let isElementFocused = (actualFocusedAXElement != nil && CFEqual(el, actualFocusedAXElement!)) || (getBoolAttribute(el, kAXFocusedAttribute as CFString) ?? false)
    let selected = getBoolAttribute(el, kAXSelectedAttribute as CFString)
    let bounds = getBounds(el)
    let actions = getActions(el)
    
    var nodeDict: [String: Any] = [
        "role": role,
        "title": title,
        "path": currentPath,
        "is_focused": isElementFocused,
        "actions": actions
    ]
    if let en = enabled { nodeDict["is_enabled"] = en }
    if let sel = selected { nodeDict["is_selected"] = sel }
    if let p = parentPath { nodeDict["parent_path"] = p }
    if let sub = subrole { nodeDict["subrole"] = sub }
    if let v = value { nodeDict["value"] = v }
    if let d = desc { nodeDict["description"] = d }
    if let ident = identifier { nodeDict["identifier"] = ident }
    if let b = bounds { nodeDict["bounds"] = b }
    
    // If this node matches the focused element, record its canonical path
    if isElementFocused && focusedUIDict != nil {
        focusedUIDict!["path"] = currentPath
    }
    
    // Check if this node is considered interactive/meaningful
    let hasText = !title.isEmpty || (value != nil && !value!.isEmpty) || (desc != nil && !desc!.isEmpty)
    let isActionable = !actions.isEmpty || interactiveRoles.contains(role)
    if isActionable && (hasText || role != "AXStaticText") {
        interactiveNodes.append(nodeDict)
    }
    
    // Check child recursion budget
    var childrenList: [[String: Any]] = []
    if depth < config.maxDepth {
        var childrenRef: CFTypeRef?
        let resChildren = AXUIElementCopyAttributeValue(el, kAXChildrenAttribute as CFString, &childrenRef)
        if resChildren == .success, let children = childrenRef as? [AXUIElement] {
            if children.count > config.maxChildrenPerNode {
                truncatedByMaxChildren = true
                isTruncated = true
            }
            var roleIndices: [String: Int] = [:]
            for child in children.prefix(config.maxChildrenPerNode) {
                let cRole = getStringAttribute(child, kAXRoleAttribute as CFString) ?? "AXUIElement"
                let idx = roleIndices[cRole] ?? 0
                roleIndices[cRole] = idx + 1
                let childPath = "\(currentPath)/\(cRole)[\(idx)]"
                
                if let childNode = traverse(child, currentPath: childPath, parentPath: currentPath, depth: depth + 1) {
                    childrenList.append(childNode)
                }
                
                if (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0 >= config.timeoutMs {
                    timedOut = true
                    isTruncated = true
                    break
                }
                if totalVisited >= config.maxElements {
                    truncatedByMaxElements = true
                    isTruncated = true
                    break
                }
            }
        }
    }
    
    nodeDict["children"] = childrenList
    return nodeDict
}

// 6. Build Root Hierarchy: Application -> Windows -> Controls
var rootChildren: [[String: Any]] = []

if !orderedWindowElements.isEmpty {
    for (wIdx, winEl) in orderedWindowElements.enumerated() {
        let winPath = "AXApplication/AXWindow[\(wIdx)]"
        if let winNode = traverse(winEl, currentPath: winPath, parentPath: "AXApplication", depth: 2) {
            rootChildren.append(winNode)
        }
        if (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0 >= config.timeoutMs || totalVisited >= config.maxElements {
            break
        }
    }
} else {
    // If no windows discovered, traverse application directly
    var childrenRef: CFTypeRef?
    if AXUIElementCopyAttributeValue(axApp, kAXChildrenAttribute as CFString, &childrenRef) == .success,
       let children = childrenRef as? [AXUIElement] {
        if children.count > config.maxChildrenPerNode {
            truncatedByMaxChildren = true
            isTruncated = true
        }
        var roleIndices: [String: Int] = [:]
        for child in children.prefix(config.maxChildrenPerNode) {
            let cRole = getStringAttribute(child, kAXRoleAttribute as CFString) ?? "AXUIElement"
            let idx = roleIndices[cRole] ?? 0
            roleIndices[cRole] = idx + 1
            let childPath = "AXApplication/\(cRole)[\(idx)]"
            if let childNode = traverse(child, currentPath: childPath, parentPath: "AXApplication", depth: 2) {
                rootChildren.append(childNode)
            }
            if (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0 >= config.timeoutMs || totalVisited >= config.maxElements {
                break
            }
        }
    }
}

var rootNode: [String: Any] = [
    "role": "AXApplication",
    "title": appName,
    "path": "AXApplication",
    "is_enabled": true,
    "is_focused": true,
    "actions": [],
    "children": rootChildren
]

let totalDurationMs = (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0

var truncationReason: String? = nil
if truncatedByMaxElements {
    truncationReason = "max_elements"
} else if timedOut {
    truncationReason = "timeout"
} else if truncatedByMaxChildren {
    truncationReason = "max_children"
}

let finalStatus = isTruncated ? "PARTIAL" : "ACCESSIBILITY_AVAILABLE"

var result: [String: Any] = [
    "status": finalStatus,
    "application": [
        "name": appName,
        "pid": Int(pid)
    ],
    "windows": windowsData,
    "active_window": activeWindowDict as Any,
    "focused_element": focusedUIDict as Any,
    "root_element": rootNode,
    "flattened_interactive": interactiveNodes,
    "stats": [
        "duration_ms": totalDurationMs,
        "elements_total": totalVisited,
        "total_nodes_visited": totalVisited,
        "interactive_nodes_count": interactiveNodes.count,
        "max_depth_reached": maxDepthReached,
        "depth_reached": maxDepthReached,
        "nodes_by_depth": nodesByDepth,
        "truncated_by_max_elements": truncatedByMaxElements,
        "truncated_by_max_children": truncatedByMaxChildren,
        "timed_out": timedOut,
        "is_truncated": isTruncated,
        "truncated_by_budget": truncationReason as Any
    ]
]

emitJSONAndExit(result)

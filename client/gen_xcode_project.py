#!/usr/bin/env python3
"""Generate Xcode project for DemoUpgrade (macOS + iPad)."""
import os, uuid

def gid(): return uuid.uuid4().hex[:24].upper()

BASE = os.path.dirname(os.path.abspath(__file__))

SOURCES = {
    "App.swift":              ("",         "App.swift"),
    "ServerManager.swift":    ("Network",  "ServerManager.swift"),
    "APIClient.swift":        ("Network",  "APIClient.swift"),
    "AnalysisResult.swift":   ("Models",   "AnalysisResult.swift"),
    "ServerConfig.swift":     ("Models",   "ServerConfig.swift"),
    "ContentView.swift":      ("Views",    "ContentView.swift"),
    "SheetMusicView.swift":   ("Views",    "SheetMusicView.swift"),
}

# ── Write plists ──
mac_plist = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleName</key><string>Demo 独自升级</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundleIdentifier</key><string>com.chenhongzhou.demoupgrade</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
</dict></plist>'''
with open(os.path.join(BASE, "macOS-Info.plist"), "w") as f: f.write(mac_plist)

ios_plist = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleName</key><string>Demo 独自升级</string>
    <key>CFBundleDisplayName</key><string>Demo 独自升级</string>
    <key>CFBundleExecutable</key><string>$(EXECUTABLE_NAME)</string>
    <key>CFBundleIdentifier</key><string>com.chenhongzhou.demoupgrade</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleIcons</key><dict>
        <key>CFBundlePrimaryIcon</key><dict>
            <key>CFBundleIconFiles</key><array><string>appicon_120</string></array>
        </dict>
    </dict>
    <key>CFBundleIcons~ipad</key><dict>
        <key>CFBundlePrimaryIcon</key><dict>
            <key>CFBundleIconFiles</key><array><string>appicon_152</string><string>appicon_167</string></array>
        </dict>
    </dict>
    <key>UISupportedInterfaceOrientations</key>
    <array><string>UIInterfaceOrientationPortrait</string><string>UIInterfaceOrientationLandscapeLeft</string><string>UIInterfaceOrientationLandscapeRight</string></array>
    <key>UISupportedInterfaceOrientations~ipad</key>
    <array><string>UIInterfaceOrientationPortrait</string><string>UIInterfaceOrientationPortraitUpsideDown</string><string>UIInterfaceOrientationLandscapeLeft</string><string>UIInterfaceOrientationLandscapeRight</string></array>
    <key>UIRequiresFullScreen</key><true/>
    <key>LSMinimumSystemVersion</key><string>16.0</string>
</dict></plist>'''
with open(os.path.join(BASE, "iOS-Info.plist"), "w") as f: f.write(ios_plist)

# ── UUIDs ──
G_PROJ    = gid(); G_MAIN    = gid(); G_SRC     = gid(); G_PROD    = gid()
G_NETWORK  = gid(); G_MODELS  = gid(); G_VIEWS   = gid()

T_MAC     = gid(); T_IOS     = gid()
P_MAC     = gid(); P_IOS     = gid()
CL_PROJ   = gid(); CL_MAC    = gid(); CL_IOS    = gid()
CFG_PDBG  = gid(); CFG_PREL  = gid()
CFG_MDBG  = gid(); CFG_MREL  = gid()
CFG_IDBG  = gid(); CFG_IREL  = gid()

file_refs   = {n: gid() for n in SOURCES}
mac_build   = {n: gid() for n in SOURCES}
ios_build   = {n: gid() for n in SOURCES}
src_phase_m = gid(); src_phase_i = gid()
res_phase_m = gid(); res_phase_i = gid()

ICNS_REF   = gid(); ICNS_BLD   = gid()
PLIST_M_REF = gid(); PLIST_I_REF = gid()

# Icon PNGs for iOS
icons = {}
for sz in [120, 152, 167, 180]:
    icons[sz] = (gid(), gid())  # (file_ref, build_ref)

pbx  = '// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {};\n'
pbx += '\tobjectVersion = 56;\n\tobjects = {\n\n'

# ─ PBXBuildFile ─
pbx += '/* Begin PBXBuildFile section */\n'
for n in SOURCES:
    pbx += f'\t\t{mac_build[n]} /* {n} (macOS) */ = {{isa = PBXBuildFile; fileRef = {file_refs[n]} /* {n} */; }};\n'
    pbx += f'\t\t{ios_build[n]} /* {n} (iOS) */ = {{isa = PBXBuildFile; fileRef = {file_refs[n]} /* {n} */; }};\n'
pbx += f'\t\t{ICNS_BLD} /* AppIcon.icns (macOS) */ = {{isa = PBXBuildFile; fileRef = {ICNS_REF} /* AppIcon.icns */; }};\n'
for sz, (ref, bld) in icons.items():
    pbx += f'\t\t{bld} /* appicon_{sz}.png (iOS) */ = {{isa = PBXBuildFile; fileRef = {ref} /* appicon_{sz}.png */; }};\n'
pbx += '/* End PBXBuildFile section */\n\n'

# ─ PBXFileReference ─
pbx += '/* Begin PBXFileReference section */\n'
pbx += f'\t\t{P_MAC} /* DemoUpgrade.app (macOS) */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = DemoUpgrade.app; sourceTree = BUILT_PRODUCTS_DIR; }};\n'
pbx += f'\t\t{P_IOS} /* DemoUpgrade.app (iOS) */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = DemoUpgrade.app; sourceTree = BUILT_PRODUCTS_DIR; }};\n'
for n, ref in file_refs.items():
    _, path = SOURCES[n]
    pbx += f'\t\t{ref} /* {n} */ = {{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "{path}"; sourceTree = "<group>"; }};\n'
pbx += f'\t\t{ICNS_REF} /* AppIcon.icns */ = {{isa = PBXFileReference; lastKnownFileType = image.icns; path = AppIcon.icns; sourceTree = "<group>"; }};\n'
for sz, (ref, _) in icons.items():
    pbx += f'\t\t{ref} /* appicon_{sz}.png */ = {{isa = PBXFileReference; lastKnownFileType = image.png; path = appicon_{sz}.png; sourceTree = "<group>"; }};\n'
pbx += f'\t\t{PLIST_M_REF} /* macOS-Info.plist */ = {{isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = macOS-Info.plist; sourceTree = "<group>"; }};\n'
pbx += f'\t\t{PLIST_I_REF} /* iOS-Info.plist */ = {{isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = iOS-Info.plist; sourceTree = "<group>"; }};\n'
pbx += '/* End PBXFileReference section */\n\n'

# ─ PBXGroup ─
pbx += '/* Begin PBXGroup section */\n'
pbx += f'\t\t{G_MAIN} = {{isa = PBXGroup; children = (\n'
pbx += f'\t\t\t{G_SRC} /* Sources */,\n'
pbx += f'\t\t\t{ICNS_REF} /* AppIcon.icns */,\n'
for sz, (ref, _) in icons.items():
    pbx += f'\t\t\t{ref} /* appicon_{sz}.png */,\n'
pbx += f'\t\t\t{PLIST_M_REF} /* macOS-Info.plist */,\n'
pbx += f'\t\t\t{PLIST_I_REF} /* iOS-Info.plist */,\n'
pbx += f'\t\t\t{G_PROD} /* Products */,\n\t\t); sourceTree = "<group>"; }};\n'

pbx += f'\t\t{G_SRC} = {{isa = PBXGroup; children = (\n'
for n in SOURCES:
    g, _ = SOURCES[n]
    if not g: pbx += f'\t\t\t{file_refs[n]} /* {n} */,\n'
pbx += f'\t\t\t{G_MODELS} /* Models */,\n\t\t\t{G_NETWORK} /* Network */,\n\t\t\t{G_VIEWS} /* Views */,\n'
pbx += f'\t\t); path = Sources/DemoUpgrade; sourceTree = "<group>"; }};\n'

for d, gid_name in [("Models", G_MODELS), ("Network", G_NETWORK), ("Views", G_VIEWS)]:
    pbx += f'\t\t{gid_name} = {{isa = PBXGroup; children = (\n'
    for n in SOURCES:
        g, _ = SOURCES[n]
        if g == d: pbx += f'\t\t\t{file_refs[n]} /* {n} */,\n'
    pbx += f'\t\t); path = {d}; sourceTree = "<group>"; }};\n'

pbx += f'\t\t{G_PROD} = {{isa = PBXGroup; children = ({P_MAC} /* macOS .app */, {P_IOS} /* iOS .app */); name = Products; sourceTree = "<group>"; }};\n'
pbx += '/* End PBXGroup section */\n\n'

# ─ PBXNativeTarget ─
pbx += '/* Begin PBXNativeTarget section */\n'
for tid, pid, name, ptype, clist, sp, rp in [
    (T_MAC, P_MAC, "DemoUpgrade-macOS", "com.apple.product-type.application", CL_MAC, src_phase_m, res_phase_m),
    (T_IOS, P_IOS, "DemoUpgrade-iOS", "com.apple.product-type.application", CL_IOS, src_phase_i, res_phase_i)]:
    pbx += f'\t\t{tid} /* {name} */ = {{isa = PBXNativeTarget; buildConfigurationList = {clist}; buildPhases = ({sp} /* Sources */, {rp} /* Resources */); buildRules = (); dependencies = (); name = {name}; productName = DemoUpgrade; productReference = {pid}; productType = "{ptype}"; }};\n'
pbx += '/* End PBXNativeTarget section */\n\n'

# ─ PBXProject ─
pbx += '/* Begin PBXProject section */\n'
pbx += f'\t\t{G_PROJ} /* Project */ = {{isa = PBXProject; attributes = {{ BuildIndependentTargetsInParallel = 1; LastSwiftUpdateCheck = 1600; }}; buildConfigurationList = {CL_PROJ}; compatibilityVersion = "Xcode 14.0"; developmentRegion = "zh-Hans"; hasScannedForEncodings = 0; knownRegions = (en, Base, "zh-Hans"); mainGroup = {G_MAIN}; productRefGroup = {G_PROD}; projectDirPath = ""; projectRoot = ""; targets = ({T_MAC}, {T_IOS}); }};\n'
pbx += '/* End PBXProject section */\n\n'

# ─ PBXSourcesBuildPhase ─
pbx += '/* Begin PBXSourcesBuildPhase section */\n'
for phase, builds in [(src_phase_m, mac_build), (src_phase_i, ios_build)]:
    pbx += f'\t\t{phase} /* Sources */ = {{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = (\n'
    for n in SOURCES: pbx += f'\t\t\t{builds[n]} /* {n} */,\n'
    pbx += f'\t\t); runOnlyForDeploymentPostprocessing = 0; }};\n'
pbx += '/* End PBXSourcesBuildPhase section */\n\n'

# ─ PBXResourcesBuildPhase ─
pbx += '/* Begin PBXResourcesBuildPhase section */\n'
pbx += f'\t\t{res_phase_m} /* Resources (macOS) */ = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ({ICNS_BLD} /* AppIcon.icns */); runOnlyForDeploymentPostprocessing = 0; }};\n'
ios_res_files = ", ".join(bld for _, (_, bld) in icons.items())
pbx += f'\t\t{res_phase_i} /* Resources (iOS) */ = {{isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ({ios_res_files}); runOnlyForDeploymentPostprocessing = 0; }};\n'
pbx += '/* End PBXResourcesBuildPhase section */\n\n'

# ─ XCBuildConfiguration ─
pbx += '/* Begin XCBuildConfiguration section */\n'

def cfg(id, name, vals):
    s = f'\t\t{id} /* {name} */ = {{isa = XCBuildConfiguration; buildSettings = {{\n'
    for k, v in vals.items():
        if isinstance(v, bool): s += f'\t\t\t{k} = {("YES" if v else "NO")};\n'
        elif isinstance(v, str): s += f'\t\t\t{k} = {v};\n'
    s += f'\t\t}}; name = {name}; }};\n'
    return s

base = {"ALWAYS_SEARCH_USER_PATHS": False, "CLANG_ENABLE_MODULES": True, "SWIFT_VERSION": "5.0", "ENABLE_USER_SCRIPT_SANDBOXING": False}

debug = {**base, "DEBUG_INFORMATION_FORMAT": "dwarf", "ENABLE_TESTABILITY": True, "GCC_OPTIMIZATION_LEVEL": "0", "SWIFT_OPTIMIZATION_LEVEL": '"-Onone"', "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "DEBUG", "MTL_ENABLE_DEBUG_INFO": "INCLUDE_SOURCE", "ONLY_ACTIVE_ARCH": True}
release = {**base, "DEBUG_INFORMATION_FORMAT": '"dwarf-with-dsym"', "GCC_OPTIMIZATION_LEVEL": "s", "SWIFT_OPTIMIZATION_LEVEL": '"-O"', "MTL_ENABLE_DEBUG_INFO": False}

mac_settings = {"CODE_SIGN_STYLE": "Automatic", "DEVELOPMENT_TEAM": "8WFH238U2W", "CURRENT_PROJECT_VERSION": "1", "MARKETING_VERSION": "1.0", "PRODUCT_BUNDLE_IDENTIFIER": "com.chenhongzhou.demoupgrade", "PRODUCT_NAME": "DemoUpgrade", "MACOSX_DEPLOYMENT_TARGET": "14.0", "GENERATE_INFOPLIST_FILE": False, "INFOPLIST_FILE": "macOS-Info.plist", "SDKROOT": "macosx", "SUPPORTED_PLATFORMS": "macosx", "SWIFT_VERSION": "5.0"}

ios_settings = {"CODE_SIGN_STYLE": "Automatic", "DEVELOPMENT_TEAM": "8WFH238U2W", "CURRENT_PROJECT_VERSION": "1", "MARKETING_VERSION": "1.0", "PRODUCT_BUNDLE_IDENTIFIER": "com.chenhongzhou.demoupgrade", "PRODUCT_NAME": "DemoUpgrade", "IPHONEOS_DEPLOYMENT_TARGET": "16.0", "TARGETED_DEVICE_FAMILY": '"1,2"', "GENERATE_INFOPLIST_FILE": False, "INFOPLIST_FILE": "iOS-Info.plist", "SDKROOT": "iphoneos", "SUPPORTED_PLATFORMS": "iphoneos", "SWIFT_VERSION": "5.0"}

pbx += cfg(CFG_PDBG, "Debug", debug)
pbx += cfg(CFG_PREL, "Release", release)
pbx += cfg(CFG_MDBG, "Debug", {**mac_settings, **debug})
pbx += cfg(CFG_MREL, "Release", {**mac_settings, **release, "VALIDATE_PRODUCT": True})
pbx += cfg(CFG_IDBG, "Debug", {**ios_settings, **debug})
pbx += cfg(CFG_IREL, "Release", {**ios_settings, **release, "VALIDATE_PRODUCT": True})
pbx += '/* End XCBuildConfiguration section */\n\n'

# ─ XCConfigurationList ─
pbx += '/* Begin XCConfigurationList section */\n'
for cl, dbg, rel in [(CL_PROJ, CFG_PDBG, CFG_PREL), (CL_MAC, CFG_MDBG, CFG_MREL), (CL_IOS, CFG_IDBG, CFG_IREL)]:
    pbx += f'\t\t{cl} = {{isa = XCConfigurationList; buildConfigurations = ({dbg}, {rel}); defaultConfigurationIsVisible = 0; defaultConfigurationName = Release; }};\n'
pbx += '/* End XCConfigurationList section */\n'

pbx += f'\t}}; rootObject = {G_PROJ} /* Project object */; }}\n'

xcodeproj = os.path.join(BASE, "DemoUpgrade.xcodeproj")
os.makedirs(xcodeproj, exist_ok=True)
with open(os.path.join(xcodeproj, "project.pbxproj"), "w") as f: f.write(pbx)

print("✅ Xcode project generated")
print(f"   Targets: DemoUpgrade-macOS + DemoUpgrade-iOS")
print(f"   macOS icon: AppIcon.icns  |  iOS icon: appicon_*.png via Info.plist")

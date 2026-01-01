#!/usr/bin/env python3
import sys, os, json, logging, sqlite3, datetime, pathlib, http.client, re, typing, zipfile, shutil, queue, socket, argparse, io, difflib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Union, Generator

from buddai_shared import DB_PATH

class CodeValidator:
    """Validate generated code before showing to user"""
    
    def find_line(self, code: str, substring: str) -> int:
        for i, line in enumerate(code.splitlines(), 1):
            if substring in line:
                return i
        return -1

    def has_safety_timeout(self, code: str) -> bool:
        # Simple heuristic: needs millis, subtraction, and a comparison to a value/constant
        # We want to avoid matching debounce logic (usually < 100ms)
        if "millis()" not in code: return False
        
        # Check for constants like SAFETY_TIMEOUT, MOTOR_TIMEOUT
        if re.search(r'>\s*[A-Z_]*TIMEOUT', code):
            return True
            
        # Check for state machine timeout (Combat Protocol)
        if "DISARM" in code and "millis" in code and ">" in code:
            return True
            
        # Check for numeric literals > 500 (Debounce is usually 50)
        comparisons = re.findall(r'>\s*(\d+)', code)
        return any(int(val) > 500 for val in comparisons)

    def matches_style(self, code: str) -> bool:
        # Placeholder for style matching logic
        return True

    def apply_style(self, code: str) -> str:
        # Placeholder for style application
        return code

    def refactor_loop_to_function(self, code: str) -> str:
        """Extract loop body into runSystemLogic()"""
        loop_match = re.search(r'void\s+loop\s*\(\s*\)\s*\{', code)
        if not loop_match: return code
        
        start_idx = loop_match.end()
        brace_count = 1
        loop_body_end = -1
        
        for i, char in enumerate(code[start_idx:], start=start_idx):
            if char == '{': brace_count += 1
            elif char == '}': brace_count -= 1
            
            if brace_count == 0:
                loop_body_end = i
                break
        
        if loop_body_end == -1: return code
        
        body = code[start_idx:loop_body_end]
        new_code = code[:start_idx] + "\n  runSystemLogic();\n" + code[loop_body_end:]
        new_code += "\n\nvoid runSystemLogic() {" + body + "}\n"
        return new_code

    def validate(self, code: str, hardware: str, user_message: str = "") -> Tuple[bool, List[Dict]]:
        """Check code against known rules"""
        issues = []
        
        # Check 1: ESP32 PWM
        if "ESP32" in hardware.upper():
            if "analogWrite" in code:
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, "analogWrite"),
                    "message": "ESP32 doesn't support analogWrite(). Use ledcWrite()",
                    "fix": lambda c: c.replace("analogWrite", "ledcWrite")
                })
        
        # Check 2: Non-blocking code
        if "delay(" in code and "motor" in code.lower():
            issues.append({
                "severity": "warning",
                "line": self.find_line(code, "delay"),
                "message": "Using delay() in motor code blocks safety checks",
                "fix": lambda c: c # No auto-fix
            })
        
        # Check 3: Safety timeout
        if ("motor" in code.lower() or "servo" in code.lower()):
            if not self.has_safety_timeout(code):
                # Context-aware stop logic
                is_servo = "Servo" in code and "L298N" not in code
                stop_logic = "    // STOP MOTORS\n    ledcWrite(0, 0);\n    ledcWrite(1, 0);"
                if is_servo:
                    stop_logic = "    // STOP SERVO\n    // Implement safe position (e.g. myServo.write(90));"

                issues.append({
                    "severity": "error",
                    "message": "Critical: No safety timeout detected (must be > 500ms).",
                    "fix": lambda c, sl=stop_logic: "#define SAFETY_TIMEOUT 5000\nunsigned long lastCommand = 0;\n" + \
                                     re.sub(r'(void\s+loop\s*\(\s*\)\s*\{)', \
                                            rf'\1\n  // [AUTO-FIX] Safety Timeout\n  if (millis() - lastCommand > SAFETY_TIMEOUT) {{\n{sl}\n  }}\n', c)
                })
        
        # Check 4: L298N PWM Pin Misuse
        pwm_pins = re.findall(r'ledcAttachPin\s*\(\s*(\w+)\s*,', code)
        for pin in pwm_pins:
            # Check if digitalWrite is used on this pin
            if re.search(r'digitalWrite\s*\(\s*' + re.escape(pin) + r'\s*,', code):
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, f"digitalWrite({pin}"),
                    "message": f"Conflict: PWM pin '{pin}' used with digitalWrite(). Use ledcWrite() for speed control.",
                    "fix": lambda c, p=pin: re.sub(r'digitalWrite\s*\(\s*' + re.escape(p) + r'\s*,\s*[^)]+\);?', f'// [Fixed] Removed conflicting digitalWrite on PWM pin {p}', c)
                })

        # Check 5: Broken Debounce Logic (Type Mismatch)
        # Example: if (buttonState != lastDebounceTime)
        bad_debounce = re.search(r'if\s*\(\s*\w+\s*[!=]=\s*\w*DebounceTime\s*\)', code)
        if bad_debounce:
            issues.append({
                "severity": "error",
                "line": self.find_line(code, bad_debounce.group(0)),
                "message": "Type Mismatch: Comparing button state (int) with time (long).",
                "fix": lambda c: c.replace(bad_debounce.group(0), "if ((millis() - lastDebounceTime) > debounceDelay)")
            })

        # Check 6: Safety Timeout Value
        timeout_match = re.search(r'#define\s+SAFETY_TIMEOUT\s+(\d+)', code)
        if timeout_match and int(timeout_match.group(1)) > 5000:
            issues.append({
                "severity": "error",
                "line": self.find_line(code, timeout_match.group(0)),
                "message": f"Safety timeout {timeout_match.group(1)}ms is too long (Max: 5000ms).",
                "fix": lambda c: re.sub(r'(#define\s+SAFETY_TIMEOUT\s+)\d+', r'\g<1>5000', c)
            })

        # Check 7: Broken Safety Timer Logic (Static Init)
        bad_static = re.search(r'static\s+unsigned\s+long\s+(\w+)\s*=\s*millis\(\);', code)
        if bad_static:
            issues.append({
                "severity": "error",
                "line": self.find_line(code, bad_static.group(0)),
                "message": "Static timer initialized with millis() prevents reset. Initialize to 0.",
                "fix": lambda c: c.replace(bad_static.group(0), f"static unsigned long {bad_static.group(1)} = 0;")
            })

        # Check 8: Incomplete Motor Logic (L298N Validation)
        # If user explicitly asks for L298N or DC Motor, OR asks for 'motor' without 'servo'
        is_l298n_request = "l298n" in user_message.lower() or "dc motor" in user_message.lower() or ("motor" in user_message.lower() and "servo" not in user_message.lower())
        
        if is_l298n_request:
            # 1. Check for Direction Pins (IN1/IN2)
            if not re.search(r'(?:#define|const\s+int)\s+\w*(?:IN1|IN2|DIR)\w*', code, re.IGNORECASE):
                issues.append({
                    "severity": "error",
                    "message": "Missing L298N Direction Pins (IN1/IN2).",
                    "fix": lambda c: "// [AUTO-FIX] L298N Definitions\n#define IN1 18\n#define IN2 19\n" + c
                })

            # 2. Check for PWM Pin (ENA)
            if not re.search(r'(?:#define|const\s+int)\s+\w*(?:ENA|ENB|PWM)\w*', code, re.IGNORECASE):
                issues.append({
                    "severity": "error",
                    "message": "Missing L298N PWM Pin (ENA).",
                    "fix": lambda c: "#define ENA 21 // [AUTO-FIX] Missing PWM Pin\n" + c
                })

            # 3. Check for Direction Control (digitalWrite)
            if "digitalWrite" not in code:
                issues.append({
                    "severity": "error",
                    "message": "L298N requires digitalWrite() for direction control.",
                    "fix": lambda c: re.sub(r'(void\s+loop\s*\(\s*\)\s*\{)', r'\1\n  // [AUTO-FIX] Set Direction\n  digitalWrite(IN1, HIGH);\n  digitalWrite(IN2, LOW);\n', c)
                })

        # Check 9: Unnecessary Wire.h
        wire_include = re.search(r'#include\s+[<"]Wire\.h[>"]', code)
        if wire_include:
            # Check if Wire is actually used (excluding the include itself)
            rest_of_code = code.replace(wire_include.group(0), "")
            if not re.search(r'\bWire\b', rest_of_code):
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, wire_include.group(0)),
                    "message": "Unnecessary #include <Wire.h> detected.",
                    "fix": lambda c: re.sub(r'#include\s+[<"]Wire\.h[>"]', '// [Auto-Fix] Removed unnecessary Wire.h', c)
                })

        # Check 10: High-Frequency Serial Logging
        if ("Serial.print" in code or "Serial.write" in code) and \
           ("motor" in code.lower() or "servo" in code.lower()):
            # Check for throttling pattern (simple heuristic for timer variables)
            if not re.search(r'(print|log|debug|serial)\s*Timer', code, re.IGNORECASE) and \
               not re.search(r'last\s*(Print|Log|Debug)', code, re.IGNORECASE):
                issues.append({
                    "severity": "warning",
                    "line": self.find_line(code, "Serial.print"),
                    "message": "Serial logging in motor loops causes jitter. Ensure it's throttled (e.g. every 100ms).",
                    "fix": lambda c: c + "\n// [Performance] Warning: Serial.print() inside loops can interrupt motor timing."
                })

        # Check 11: Feature Bloat (Unrequested Button)
        if user_message:
            msg_lower = user_message.lower()
            # If user didn't ask for inputs/buttons
            if not any(w in msg_lower for w in ['button', 'switch', 'input', 'trigger']):
                # Pattern 1: Variable assignment (int btn = digitalRead(...))
                for match in re.finditer(r'(?:int|bool|byte)\s+(\w*(?:button|btn|switch)\w*)\s*=\s*digitalRead\s*\([^;]+;', code, re.IGNORECASE):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, match.group(0)),
                        "message": f"Feature Bloat: Unrequested button code detected ('{match.group(1)}').",
                        "fix": lambda c, m=match.group(0): c.replace(m, "")
                    })
                
                # Pattern 2: Direct usage in conditions (if (digitalRead(BUTTON_PIN)...))
                for match in re.finditer(r'digitalRead\s*\(\s*(\w*(?:BUTTON|BTN|SWITCH)\w*)\s*\)', code, re.IGNORECASE):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, match.group(0)),
                        "message": f"Feature Bloat: Unrequested button check detected ('{match.group(1)}').",
                        "fix": lambda c, m=match.group(0): c.replace(m, "0")
                    })
                
                # Pattern 3: pinMode(..., INPUT)
                for match in re.finditer(r'pinMode\s*\(\s*\w+\s*,\s*INPUT(?:_PULLUP)?\s*\);', code):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, match.group(0)),
                        "message": "Feature Bloat: Unrequested input pin configuration.",
                        "fix": lambda c, m=match.group(0): c.replace(m, "")
                    })
                
                # Pattern 4: Unused button variable initialization (int btn = LOW;)
                for match in re.finditer(r'(?:int|bool|byte)\s+(\w*(?:button|btn|switch)\w*)\s*=\s*(?:LOW|HIGH|0|1|false|true)\s*;', code, re.IGNORECASE):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, match.group(0)),
                        "message": f"Feature Bloat: Unused button variable '{match.group(1)}'.",
                        "fix": lambda c, m=match.group(0): c.replace(m, "")
                    })

        # Check 14: State Machine for Weapons (Combat Protocol)
        if "weapon" in user_message.lower() or "combat" in user_message.lower() or "state machine" in user_message.lower():
            if "enum" not in code and "bool isArmed" not in code:
                 issues.append({
                    "severity": "error",
                    "message": "Combat code requires a State Machine (enum State or bool isArmed).",
                    "fix": lambda c: c.replace("void setup", "\n// [AUTO-FIX] State Machine\nenum State { DISARMED, ARMING, ARMED, FIRING };\nState currentState = DISARMED;\nunsigned long stateTimer = 0;\n\nvoid setup") if "void setup" in c else "// [AUTO-FIX] State Machine\nenum State { DISARMED, ARMING, ARMED, FIRING };\nState currentState = DISARMED;\n" + c
                })
            
            if "Serial.read" not in code and "Serial.available" not in code:
                 issues.append({
                    "severity": "error",
                    "message": "Missing Serial Command handling (e.g., 'A' to Arm).",
                    "fix": lambda c: c.replace("void loop() {", "void loop() {\n  if (Serial.available()) {\n    char cmd = Serial.read();\n    // Handle commands\n  }\n")
                })

        # Check 15: Function Naming Conventions (camelCase)
        # Exclude standard Arduino functions
        func_defs = re.finditer(r'\b(void|int|bool|float|double|String|char|long|unsigned(?:\s+long)?)\s+([a-zA-Z0-9_]+)\s*\(', code)
        for match in func_defs:
            func_name = match.group(2)
            if func_name in ['setup', 'loop', 'main']: continue
            
            # Check if camelCase (starts with lowercase, no underscores unless specific style)
            if not re.match(r'^[a-z][a-zA-Z0-9]*$', func_name):
                # Check if it's snake_case or PascalCase
                suggestion = func_name
                if '_' in func_name: # snake_case -> camelCase
                    components = func_name.split('_')
                    suggestion = components[0].lower() + ''.join(x.title() for x in components[1:])
                elif func_name[0].isupper(): # PascalCase -> camelCase
                    suggestion = func_name[0].lower() + func_name[1:]
                
                issues.append({
                    "severity": "warning",
                    "line": self.find_line(code, match.group(0)),
                    "message": f"Style: Function '{func_name}' should be camelCase (e.g., '{suggestion}').",
                    "fix": lambda c, old=func_name, new=suggestion: c.replace(old, new)
                })

        # Check 16: Monolithic Code Structure
        if "function" in user_message.lower() or "naming" in user_message.lower() or "modular" in user_message.lower():
            has_custom_funcs = False
            for match in re.finditer(r'\b(void|int|bool|float|double|String|char|long|unsigned(?:\s+long)?)\s+([a-zA-Z0-9_]+)\s*\(', code):
                if match.group(2) not in ['setup', 'loop', 'main']:
                    has_custom_funcs = True
                    break
            
            if not has_custom_funcs:
                issues.append({
                    "severity": "error",
                    "message": "Structure Violation: Request asked for functions but code is monolithic.",
                    "fix": lambda c: c.replace("void loop() {", "void loop() {\n  runSystemLogic();\n}\n\nvoid runSystemLogic() {") + "\n}"
                })

        # Check 17: Loop Length (Modularity)
        if "function" in user_message.lower() or "naming" in user_message.lower() or "modular" in user_message.lower():
            loop_match = re.search(r'void\s+loop\s*\(\s*\)\s*\{', code)
            if loop_match:
                start_idx = loop_match.end()
                brace_count = 1
                loop_body = ""
                
                for char in code[start_idx:]:
                    if char == '{': brace_count += 1
                    elif char == '}': brace_count -= 1
                    
                    if brace_count == 0:
                        break
                    loop_body += char
                
                # Count significant lines
                lines = [line.strip() for line in loop_body.split('\n')]
                significant_lines = [l for l in lines if l and not l.startswith('//') and not l.startswith('/*') and l != '']
                
                if len(significant_lines) >= 10:
                    issues.append({
                        "severity": "error",
                        "message": f"Modularity Violation: loop() has {len(significant_lines)} lines (limit 10). Move logic to functions.",
                        "fix": lambda c: self.refactor_loop_to_function(c)
                    })

        # Check 18: ADC Resolution (ESP32)
        if "ESP32" in hardware.upper():
            adc_res_match = re.search(r'#define\s+(\w*ADC\w*RES\w*)\s+(\d+)', code, re.IGNORECASE)
            if adc_res_match:
                val = int(adc_res_match.group(2))
                if val not in [4095, 4096]:
                     issues.append({
                        "severity": "error",
                        "line": self.find_line(code, adc_res_match.group(0)),
                        "message": f"Hardware Mismatch: ESP32 ADC is 12-bit (4095), not {val}.",
                        "fix": lambda c, old=adc_res_match.group(0), name=adc_res_match.group(1): c.replace(old, f"#define {name} 4095")
                    })
            
            # Check 20: Hardcoded 10-bit ADC math
            # Matches / 1023, / 1023.0, / 1024.0 (avoiding / 1024 int for bytes)
            for match in re.finditer(r'/\s*(1023(?:\.0?)?f?|1024(?:\.0)f?)', code):
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, match.group(0)),
                    "message": "Hardware Mismatch: ESP32 ADC is 12-bit. Use 4095.0, not 1023/1024.",
                    "fix": lambda c, m=match.group(0): c.replace(m, "/ 4095.0")
                })

        # Check 21: Status LED Pattern
        if "status" in user_message.lower() and ("led" in user_message.lower() or "indicator" in user_message.lower()):
            # Detect breathing logic (incrementing duty cycle in loop)
            breathing_match = re.search(r'(?:dutyCycle|brightness)\s*(\+=|\+\+|\-=|\-\-)', code)
            if breathing_match:
                issues.append({
                    "severity": "error",
                    "line": self.find_line(code, breathing_match.group(0)),
                    "message": "Wrong Pattern: Status indicators should use Blink Patterns (States), not Breathing/Fading.",
                    "fix": lambda c: c + "\n// [Fix Required] Implement setStatusLED(LEDStatus state) instead of fading."
                })

            # Check for missing Enum
            if not re.search(r'enum\s+(?:StatusState|LEDStatus)\s*\{', code):
                issues.append({
                    "severity": "error",
                    "message": "Missing Status Enum: Status LEDs require a state machine (enum LEDStatus {OFF, IDLE, ACTIVE, ERROR}).",
                    "fix": lambda c: c.replace("void setup", "\n// [AUTO-FIX] Status Enum\nenum LEDStatus { OFF, IDLE, ACTIVE, ERROR };\nLEDStatus currentStatus = IDLE;\nunsigned long lastBlink = 0;\n\nvoid setup") if "void setup" in c else "// [AUTO-FIX] Status Enum\nenum LEDStatus { OFF, IDLE, ACTIVE, ERROR };\nLEDStatus currentStatus = IDLE;\nunsigned long lastBlink = 0;\n" + c
                })

        # Check 19: Unnecessary Debouncing (Analog/Battery)
        if "battery" in user_message.lower() or "voltage" in user_message.lower() or "analog" in user_message.lower():
            if "button" not in user_message.lower():
                debounce_match = re.search(r'(?:debounce|lastDebounceTime)', code, re.IGNORECASE)
                if debounce_match:
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, debounce_match.group(0)),
                        "message": "Logic Error: Debouncing detected in analog/battery code. Analog sensors don't need debouncing.",
                        "fix": lambda c: re.sub(r'.*debounce.*', '// [Fixed] Removed unnecessary debounce logic', c, flags=re.IGNORECASE)
                    })

        # Check 12: Undefined Pin Constants
        pin_vars = set(re.findall(r'(?:digitalRead|digitalWrite|pinMode|ledcAttachPin)\s*\(\s*([a-zA-Z_]\w+)', code))
        for var in pin_vars:
            if var in ['LED_BUILTIN', 'HIGH', 'LOW', 'INPUT', 'OUTPUT', 'INPUT_PULLUP', 'true', 'false']:
                continue
            
            # Check if defined
            is_defined = re.search(r'#define\s+' + re.escape(var) + r'\b', code) or \
                         re.search(r'\b(?:const\s+)?(?:int|byte|uint8_t|short)\s+' + re.escape(var) + r'\s*=', code)
            
            if not is_defined:
                issues.append({
                    "severity": "error",
                    "message": f"Undefined variable '{var}' used in pin operation.",
                    "fix": lambda c, v=var: f"#define {v} 2 // [Auto-Fix] Defined missing pin\n" + c
                })
        
        # Check 22: Misused Debouncing (Animation Timing)
        if "brightness" in code or "fade" in code:
            misused_debounce = re.search(r'if\s*\(\s*\(?\s*millis\(\)\s*-\s*\w+\s*\)?\s*>\s*(\w*DEBOUNCE\w*)\s*\)\s*\{', code, re.IGNORECASE)
            if misused_debounce:
                var_name = misused_debounce.group(1)
                # Check if the block actually modifies brightness (simple heuristic lookahead)
                start_index = misused_debounce.end()
                snippet = code[start_index:start_index+200]
                if any(x in snippet for x in ['brightness', 'fade', 'dutyCycle', 'ledcWrite']):
                    issues.append({
                        "severity": "error",
                        "line": self.find_line(code, var_name),
                        "message": f"Semantic Error: Using {var_name} for animation/fading. Use UPDATE_INTERVAL or FADE_SPEED.",
                        "fix": lambda c, v=var_name: c.replace(v, "FADE_SPEED" if v.isupper() else "fadeSpeed")
                    })

        # Check 24: Unused Variables in Setup
        setup_match = re.search(r'void\s+setup\s*\(\s*\)\s*\{', code)
        if setup_match:
            start_idx = setup_match.end()
            brace_count = 1
            setup_body = ""
            for char in code[start_idx:]:
                if char == '{': brace_count += 1
                elif char == '}': brace_count -= 1
                if brace_count == 0: break
                setup_body += char
            
            clean_body = re.sub(r'//.*', '', setup_body)
            clean_body = re.sub(r'/\*.*?\*/', '', clean_body, flags=re.DOTALL)

            local_vars = re.finditer(r'\b((?:static\s+)?(?:const\s+)?(?:int|float|bool|char|String|long|double|byte|uint8_t|unsigned(?:\s+long)?))\s+([a-zA-Z_]\w*)\s*(?:=|;)', clean_body)
            
            for match in local_vars:
                var_type = match.group(1)
                var_name = match.group(2)
                if len(re.findall(r'\b' + re.escape(var_name) + r'\b', clean_body)) == 1:
                    issues.append({
                        "severity": "warning",
                        "line": self.find_line(code, f"{var_type} {var_name}"),
                        "message": f"Unused variable '{var_name}' in setup().",
                        "fix": lambda c, v=var_name, t=var_type: re.sub(r'\b' + re.escape(t) + r'\s+' + re.escape(v) + r'[^;]*;\s*', '', c)
                    })

        # Check 25: Missing Serial.begin
        if re.search(r'Serial\.(?:print|write|println|printf)', code) and not re.search(r'Serial\.begin\s*\(', code):
            issues.append({
                "severity": "error",
                "message": "Missing Serial.begin() initialization.",
                "fix": lambda c: re.sub(r'void\s+setup\s*\(\s*\)\s*\{', r'void setup() {\n  Serial.begin(115200);', c, count=1)
            })

        # Check 26: Missing Wire.begin
        if re.search(r'Wire\.(?!h\b|begin\b)', code) and not re.search(r'Wire\.begin\s*\(', code):
            issues.append({
                "severity": "error",
                "message": "Missing Wire.begin() initialization for I2C.",
                "fix": lambda c: re.sub(r'void\s+setup\s*\(\s*\)\s*\{', r'void setup() {\n  Wire.begin();', c, count=1)
            })

        return len([i for i in issues if i['severity'] == 'error']) == 0, issues
    
    def auto_fix(self, code: str, issues: List[Dict]) -> str:
        """Automatically fix known issues"""
        fixed_code = code
        
        for issue in issues:
            if 'fix' in issue and issue['severity'] == 'error':
                fixed_code = issue['fix'](fixed_code)
        
        return fixed_code



class HardwareProfile:
    """Learn hardware-specific patterns"""
    
    ESP32_PATTERNS = {
        "pwm_setup": {
            "correct": "ledcSetup(channel, freq, resolution)",
            "wrong": ["analogWrite", "pwmWrite"],
            "learned_from": "James's corrections"
        },
        "serial_baud": {
            "preferred": 115200,
            "alternatives": [9600, 57600],
            "confidence": 1.0
        },
        "safety_timeout": {
            "standard": 5000,
            "pattern": "millis() - lastTime > TIMEOUT",
            "confidence": 1.0
        }
    }
    
    HARDWARE_KEYWORDS = {
        "ESP32-C3": ["esp32", "esp32c3", "c3", "esp-32"],
        "Arduino Uno": ["uno", "arduino uno", "atmega328p"],
        "Raspberry Pi Pico": ["pico", "rp2040"]
    }

    def detect_hardware(self, message: str) -> Optional[str]:
        msg_lower = message.lower()
        for hw, keywords in self.HARDWARE_KEYWORDS.items():
            if any(k in msg_lower for k in keywords):
                return hw
        return None
    
    def apply_hardware_rules(self, code: str, hardware: str) -> str:
        """Apply known hardware patterns"""
        if hardware == "ESP32-C3":
            # Apply ESP32-specific fixes
            code = self.fix_pwm(code)
            code = self.fix_serial(code)
            code = self.add_safety(code)
        return code

    def fix_pwm(self, code: str) -> str:
        for wrong in self.ESP32_PATTERNS["pwm_setup"]["wrong"]:
            if wrong in code:
                if wrong == "analogWrite":
                    code = code.replace("analogWrite", "ledcWrite")
        return code

    def fix_serial(self, code: str) -> str:
        preferred = self.ESP32_PATTERNS["serial_baud"]["preferred"]
        return re.sub(r'Serial\.begin\(\s*\d+\s*\)', f'Serial.begin({preferred})', code)

    def add_safety(self, code: str) -> str:
        if "motor" in code.lower() and "millis()" not in code:
             code += "\n// [BuddAI Safety] Warning: No non-blocking timeout detected. Consider adding safety timeout."
        return code



class LearningMetrics:
    """Measure BuddAI's improvement over time"""
    
    def calculate_accuracy(self):
        """What % of code is accepted without correction?"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_responses,
                COUNT(CASE WHEN f.positive = 1 THEN 1 END) as positive_feedback,
                COUNT(CASE WHEN c.id IS NOT NULL THEN 1 END) as corrected
            FROM messages m
            LEFT JOIN feedback f ON m.id = f.message_id
            LEFT JOIN corrections c ON m.content LIKE '%' || c.original_code || '%'
            WHERE m.role = 'assistant'
            AND m.timestamp > ?
        """, (thirty_days_ago,))
        
        total, positive, corrected = cursor.fetchone()
        conn.close()
        
        accuracy = (positive / total) * 100 if total and total > 0 else 0
        correction_rate = (corrected / total) * 100 if total and total > 0 else 0
        
        return {
            "accuracy": accuracy,
            "correction_rate": correction_rate,
            "improvement": self.calculate_trend()
        }
    
    def calculate_trend(self):
        """Is BuddAI getting better over time?"""
        # Compare last 7 days vs previous 7 days
        recent = self.get_accuracy_for_period(7)
        previous = self.get_accuracy_for_period(7, offset=7)
        
        improvement = recent - previous
        return f"+{improvement:.1f}%" if improvement > 0 else f"{improvement:.1f}%"

    def get_accuracy_for_period(self, days: int, offset: int = 0) -> float:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        start_dt = (datetime.now() - timedelta(days=days + offset)).isoformat()
        end_dt = (datetime.now() - timedelta(days=offset)).isoformat()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN f.positive = 1 THEN 1 END) as positive
            FROM messages m
            LEFT JOIN feedback f ON m.id = f.message_id
            WHERE m.role = 'assistant'
            AND m.timestamp BETWEEN ? AND ?
        """, (start_dt, end_dt))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return 0.0
            
        total, positive = row
        return (positive / total) * 100 if total and total > 0 else 0.0

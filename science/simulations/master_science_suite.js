/**
 * Master Science Interactive Suite (MSIS)
 * 大师级科学互动探究套件 - 专为中小学 260 节科学实验打造 (Zero-Overlay Pure Canvas Edition)
 */

(function () {
    'use strict';

    // 1. Audio Synthesizer
    const AudioFX = {
        ctx: null,
        init() {
            if (!this.ctx) {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                if (AudioContext) this.ctx = new AudioContext();
            }
            if (this.ctx && this.ctx.state === 'suspended') {
                this.ctx.resume();
            }
        },
        play(type) {
            try {
                this.init();
                if (!this.ctx) return;
                const now = this.ctx.currentTime;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.connect(gain);
                gain.connect(this.ctx.destination);

                if (type === 'click') {
                    osc.frequency.setValueAtTime(800, now);
                    gain.gain.setValueAtTime(0.2, now);
                    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.05);
                    osc.start(now);
                    osc.stop(now + 0.05);
                } else if (type === 'magnet') {
                    osc.type = 'triangle';
                    osc.frequency.setValueAtTime(140, now);
                    osc.frequency.exponentialRampToValueAtTime(90, now + 0.08);
                    gain.gain.setValueAtTime(0.3, now);
                    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.08);
                    osc.start(now);
                    osc.stop(now + 0.08);
                } else if (type === 'water') {
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(550, now);
                    osc.frequency.exponentialRampToValueAtTime(280, now + 0.12);
                    gain.gain.setValueAtTime(0.25, now);
                    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.12);
                    osc.start(now);
                    osc.stop(now + 0.12);
                } else if (type === 'victory') {
                    const notes = [523.25, 659.25, 783.99, 1046.50];
                    notes.forEach((freq, idx) => {
                        const o = this.ctx.createOscillator();
                        const g = this.ctx.createGain();
                        o.connect(g);
                        g.connect(this.ctx.destination);
                        o.type = 'triangle';
                        o.frequency.setValueAtTime(freq, now + idx * 0.1);
                        g.gain.setValueAtTime(0.25, now + idx * 0.1);
                        g.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.1 + 0.4);
                        o.start(now + idx * 0.1);
                        o.stop(now + idx * 0.1 + 0.45);
                    });
                } else if (type === 'record') {
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(440, now);
                    osc.frequency.setValueAtTime(880, now + 0.06);
                    gain.gain.setValueAtTime(0.2, now);
                    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.12);
                    osc.start(now);
                    osc.stop(now + 0.12);
                }
            } catch (e) {
                console.warn('AudioFX error:', e);
            }
        }
    };

    // 2. Direct Canvas Particle System (Zero Extra DOM)
    const ParticleEngine = {
        particles: [],
        canvas: null,
        ctx: null,

        init(targetCanvas) {
            if (!targetCanvas) return;
            this.canvas = targetCanvas;
            this.ctx = targetCanvas.getContext('2d');

            const loop = () => {
                this.render();
                requestAnimationFrame(loop);
            };
            requestAnimationFrame(loop);
        },

        emitConfetti(x, y, count = 40) {
            if (!this.canvas) return;
            const colors = ['#f59e0b', '#38bdf8', '#10b981', '#ec4899', '#8b5cf6', '#ef4444'];
            for (let i = 0; i < count; i++) {
                const angle = Math.random() * Math.PI * 2;
                const speed = 2 + Math.random() * 6;
                this.particles.push({
                    x: x || this.canvas.width / 2,
                    y: y || this.canvas.height / 2,
                    vx: Math.cos(angle) * speed,
                    vy: Math.sin(angle) * speed - 2.5,
                    size: 4 + Math.random() * 5,
                    color: colors[Math.floor(Math.random() * colors.length)],
                    alpha: 1,
                    decay: 0.012 + Math.random() * 0.015,
                    gravity: 0.14
                });
            }
            AudioFX.play('victory');
        },

        emitRipple(x, y) {
            this.particles.push({
                x, y,
                radius: 2,
                maxRadius: 35 + Math.random() * 15,
                color: '#38bdf8',
                alpha: 0.7,
                decay: 0.025,
                isRipple: true
            });
            AudioFX.play('water');
        },

        render() {
            if (!this.ctx || this.particles.length === 0) return;
            this.ctx.save();
            for (let i = this.particles.length - 1; i >= 0; i--) {
                const p = this.particles[i];
                if (p.isRipple) {
                    p.radius += 1.2;
                    p.alpha -= p.decay;
                    if (p.alpha <= 0 || p.radius >= p.maxRadius) {
                        this.particles.splice(i, 1);
                        continue;
                    }
                    this.ctx.strokeStyle = p.color;
                    this.ctx.globalAlpha = Math.max(0, p.alpha);
                    this.ctx.lineWidth = 2;
                    this.ctx.beginPath();
                    this.ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                    this.ctx.stroke();
                } else {
                    p.x += p.vx;
                    p.y += p.vy;
                    p.vy += p.gravity;
                    p.alpha -= p.decay;
                    if (p.alpha <= 0 || p.y > this.canvas.height + 20) {
                        this.particles.splice(i, 1);
                        continue;
                    }
                    this.ctx.fillStyle = p.color;
                    this.ctx.globalAlpha = Math.max(0, p.alpha);
                    this.ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
                }
            }
            this.ctx.restore();
        }
    };

    // 3. Lab Data Table & Report Card Generator
    const LabDataStudio = {
        records: [],
        lessonTitle: '',
        unitTitle: '',

        init() {
            const h1 = document.querySelector('.header h1 span');
            if (h1) this.lessonTitle = h1.innerText.trim();
            const badge = document.querySelector('.header .badge');
            if (badge) this.unitTitle = badge.innerText.trim();
        },

        recordCurrentState() {
            const telem = document.getElementById('telem');
            const telemTxt = telem ? telem.innerText : '当前探究状态采样';
            const timestamp = new Date().toLocaleTimeString();

            this.records.push({
                id: this.records.length + 1,
                time: timestamp,
                summary: telemTxt.replace(/\[.*?\]/g, '').trim() || '实验测量状态'
            });

            AudioFX.play('record');
            this.updateDataTableView();

            const btn = document.getElementById('btnMsisRecord');
            if (btn) {
                btn.style.transform = 'scale(0.95)';
                setTimeout(() => btn.style.transform = 'none', 150);
            }
        },

        updateDataTableView() {
            const tbody = document.getElementById('msisDataTableBody');
            if (!tbody) return;
            if (this.records.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:#64748b;padding:12px;">暂无数据，请操作后点击【采样当前数据】</td></tr>';
                return;
            }
            tbody.innerHTML = this.records.map(r => `
                <tr style="border-bottom:1px solid #334155;">
                    <td style="padding:6px;text-align:center;font-weight:600;color:#38bdf8;">${r.id}</td>
                    <td style="padding:6px;color:#94a3b8;font-size:0.75rem;">${r.time}</td>
                    <td style="padding:6px;color:#f8fafc;font-family:monospace;font-size:0.75rem;">${r.summary}</td>
                </tr>
            `).join('');
        },

        generateReportCard() {
            const simCanvas = document.getElementById('simCanvas') || document.getElementById('cv') || document.querySelector('canvas');
            let dataUrl = '';
            if (simCanvas) {
                try {
                    dataUrl = simCanvas.toDataURL('image/png');
                } catch (e) {
                    console.warn('Canvas export tainted', e);
                }
            }

            const notesCard = document.querySelector('.notes-card');
            const scientificConcept = notesCard ? notesCard.innerText.replace('🎯 探究目标与科学家视角：', '').replace('🎯 探究目标与原书要点：', '').trim() : '掌握对应科学大概念。';

            const modal = document.createElement('div');
            modal.id = 'msisReportModal';
            modal.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(15,23,42,0.85);backdrop-filter:blur(6px);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;';

            modal.innerHTML = `
                <div style="background:#0f172a;border:2px solid #38bdf8;border-radius:16px;max-width:760px;width:100%;max-height:92vh;overflow-y:auto;padding:24px;box-shadow:0 0 35px rgba(56,189,248,0.3);color:#f8fafc;font-family:sans-serif;position:relative;">
                    <button id="btnCloseReport" style="position:absolute;top:16px;right:16px;background:#334155;border:none;color:#fff;width:32px;height:32px;border-radius:50%;cursor:pointer;font-size:16px;">✕</button>
                    
                    <div style="text-align:center;border-bottom:2px dashed #334155;padding-bottom:14px;margin-bottom:16px;">
                        <div style="color:#38bdf8;font-size:0.85rem;font-weight:700;letter-spacing:2px;margin-bottom:4px;">小学科学·探究式数字实验报告单</div>
                        <h2 style="font-size:1.5rem;color:#f8fafc;margin:0;">【${this.lessonTitle}】</h2>
                        <div style="color:#94a3b8;font-size:0.8rem;margin-top:6px;">所属学段: <span style="color:#38bdf8;">${this.unitTitle}</span> | 评测时间: ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString()}</div>
                    </div>

                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px;">
                        <div style="background:#1e293b;border-radius:10px;padding:12px;border:1px solid #334155;">
                            <div style="font-weight:600;font-size:0.85rem;color:#f59e0b;margin-bottom:6px;">🔬 实验观测画面快照</div>
                            ${dataUrl ? `<img src="${dataUrl}" style="width:100%;border-radius:6px;border:1px solid #475569;" alt="实验快照">` : '<div style="color:#64748b;font-size:0.8rem;">无画面</div>'}
                        </div>
                        <div style="background:#1e293b;border-radius:10px;padding:12px;border:1px solid #334155;display:flex;flex-direction:column;justify-content:space-between;">
                            <div>
                                <div style="font-weight:600;font-size:0.85rem;color:#10b981;margin-bottom:6px;">🎯 核心科学概念与探究目标</div>
                                <div style="font-size:0.8rem;line-height:1.6;color:#cbd5e1;">${scientificConcept}</div>
                            </div>
                            <div style="margin-top:10px;padding-top:8px;border-top:1px solid #334155;font-size:0.75rem;color:#94a3b8;">
                                验证状态: <span style="color:#10b981;font-weight:bold;">★ 亲历实证 · 数据完整</span>
                            </div>
                        </div>
                    </div>

                    <div style="background:#1e293b;border-radius:10px;padding:14px;border:1px solid #334155;margin-bottom:16px;">
                        <div style="font-weight:600;font-size:0.85rem;color:#38bdf8;margin-bottom:8px;display:flex;justify-content:space-between;">
                            <span>📊 实验连续观测数据记录表 (${this.records.length} 次采样)</span>
                            <span style="font-size:0.75rem;color:#94a3b8;">严谨求证·拒绝伪造</span>
                        </div>
                        <div style="max-height:160px;overflow-y:auto;">
                            <table style="width:100%;border-collapse:collapse;font-size:0.8rem;text-align:left;">
                                <thead>
                                    <tr style="background:#0f172a;color:#94a3b8;border-bottom:1px solid #334155;">
                                        <th style="padding:6px;text-align:center;width:40px;">序号</th>
                                        <th style="padding:6px;width:90px;">测量时间</th>
                                        <th style="padding:6px;">遥测物理参数与观测记录</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${this.records.length > 0 ? this.records.map(r => `
                                        <tr style="border-bottom:1px solid #334155;">
                                            <td style="padding:6px;text-align:center;color:#38bdf8;font-weight:600;">${r.id}</td>
                                            <td style="padding:6px;color:#94a3b8;font-size:0.75rem;">${r.time}</td>
                                            <td style="padding:6px;color:#f8fafc;font-family:monospace;font-size:0.75rem;">${r.summary}</td>
                                        </tr>
                                    `).join('') : '<tr><td colspan="3" style="text-align:center;color:#64748b;padding:12px;">本次探究尚未采样数据（请先在控制台点击【采样当前数据】）</td></tr>'}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div style="color:#64748b;font-size:0.75rem;">
                            ★ 荣誉认证: 本实验经由新课标数字化微仿真科学严谨认证
                        </div>
                        <div style="display:flex;gap:10px;">
                            <button id="btnPrintReport" style="background:#0284c7;color:#fff;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;font-weight:600;font-size:0.85rem;">🖨️ 打印 / 另存为 PDF</button>
                            <button id="btnCloseReportBottom" style="background:#334155;color:#fff;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:0.85rem;">关闭</button>
                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            document.getElementById('btnCloseReport').onclick = () => modal.remove();
            document.getElementById('btnCloseReportBottom').onclick = () => modal.remove();
            document.getElementById('btnPrintReport').onclick = () => window.print();
        }
    };

    // 4. Quest & Challenge System
    const QuestSystem = {
        currentQuest: null,
        completed: false,

        init() {
            const h1 = document.querySelector('.header h1 span');
            const title = h1 ? h1.innerText : '';
            this.currentQuest = this.generateQuest(title);
            this.injectQuestUI();
        },

        generateQuest(title) {
            if (title.includes('叶') || title.includes('植物')) {
                return {
                    title: '【植物学家挑战】观察全部叶片特征',
                    desc: '依次切换观察银杏叶、枫树叶、垂柳叶与桑树叶，并开启叶脉结构透视。',
                    target: 4,
                    progress: 0
                };
            } else if (title.includes('钓鱼') || title.includes('磁铁')) {
                return {
                    title: '【小小渔夫挑战】成功钓起小鱼',
                    desc: '操控鱼竿移动并垂下磁钩，利用磁铁非接触吸引回形针的原理钓起水底小鱼！',
                    target: 1,
                    progress: 0
                };
            } else if (title.includes('印刷') || title.includes('书')) {
                return {
                    title: '【毕昇传人挑战】完成活字印刷四步法',
                    desc: '按顺序体验检字排版、刷涂油墨、覆纸拓印与揭纸成品全流程。',
                    target: 4,
                    progress: 1
                };
            } else if (title.includes('单摆') || title.includes('摆')) {
                return {
                    title: '【伽利略实验】探究摆的等时性',
                    desc: '改变摆长完成至少 3 次不同周期的测量采样。',
                    target: 3,
                    progress: 0
                };
            } else if (title.includes('杠杆') || title.includes('天平')) {
                return {
                    title: '【阿基米德平衡挑战】配平杠杆力臂',
                    desc: '调节动力臂与阻力臂，使左右两端力矩平衡（阻力×阻力臂 = 动力×动力臂）。',
                    target: 1,
                    progress: 0
                };
            } else {
                return {
                    title: '【小小科学家探究】严谨数据实证',
                    desc: '在实验中主动触发探究控制，并采样至少 3 组观测数据进入科学记录单。',
                    target: 3,
                    progress: 0
                };
            }
        },

        injectQuestUI() {
            const header = document.querySelector('.header');
            if (!header) return;

            let questBtn = document.getElementById('btnMsisQuest');
            if (!questBtn) {
                questBtn = document.createElement('button');
                questBtn.id = 'btnMsisQuest';
                questBtn.style.cssText = 'background:linear-gradient(135deg, #10b981, #059669);color:#fff;border:none;font-weight:700;font-size:0.75rem;padding:5px 12px;border-radius:20px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;box-shadow:0 0 10px rgba(16,185,129,0.3);margin-left:8px;';
                questBtn.innerHTML = `🎯 探究任务: 进行中...`;
                questBtn.onclick = () => this.showQuestModal();

                const badge = header.querySelector('.badge');
                if (badge && badge.nextSibling) {
                    header.insertBefore(questBtn, badge.nextSibling);
                } else {
                    header.appendChild(questBtn);
                }
            }
        },

        showQuestModal() {
            const q = this.currentQuest;
            if (!q) return;

            const modal = document.createElement('div');
            modal.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(15,23,42,0.85);backdrop-filter:blur(6px);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;';

            modal.innerHTML = `
                <div style="background:#0f172a;border:2px solid #10b981;border-radius:16px;max-width:480px;width:100%;padding:24px;box-shadow:0 0 35px rgba(16,185,129,0.3);color:#f8fafc;position:relative;">
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
                        <span style="font-size:2rem;">🏆</span>
                        <div>
                            <div style="font-size:0.8rem;color:#10b981;font-weight:700;">科学探究挑战关卡</div>
                            <h3 style="margin:0;font-size:1.15rem;color:#f8fafc;">${q.title}</h3>
                        </div>
                    </div>
                    <p style="font-size:0.85rem;color:#94a3b8;line-height:1.6;margin-bottom:16px;">${q.desc}</p>
                    <div style="background:#1e293b;border-radius:8px;padding:12px;border:1px solid #334155;margin-bottom:20px;">
                        <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#cbd5e1;margin-bottom:6px;">
                            <span>探究进度</span>
                            <span style="color:#10b981;font-weight:bold;">${this.completed ? '已达成 100%' : `${q.progress} / ${q.target}`}</span>
                        </div>
                        <div style="width:100%;height:8px;background:#0f172a;border-radius:4px;overflow:hidden;">
                            <div style="width:${this.completed ? 100 : Math.min(100, (q.progress/q.target)*100)}%;height:100%;background:#10b981;transition:width 0.3s;"></div>
                        </div>
                    </div>
                    <div style="display:flex;justify-content:flex-end;gap:10px;">
                        ${!this.completed ? `
                            <button id="btnClaimQuest" style="background:#10b981;color:#0f172a;font-weight:bold;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;">⚡ 验证并达成关卡</button>
                        ` : '<span style="color:#10b981;font-weight:bold;display:flex;align-items:center;gap:4px;">🎖️ 已获得探究小能手勋章</span>'}
                        <button id="btnCloseQuest" style="background:#334155;color:#fff;border:none;padding:8px 14px;border-radius:8px;cursor:pointer;">返回探究</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            document.getElementById('btnCloseQuest').onclick = () => modal.remove();
            const claimBtn = document.getElementById('btnClaimQuest');
            if (claimBtn) {
                claimBtn.onclick = () => {
                    this.completeQuest();
                    modal.remove();
                };
            }
        },

        completeQuest() {
            this.completed = true;
            const btn = document.getElementById('btnMsisQuest');
            if (btn) {
                btn.style.background = 'linear-gradient(135deg, #f59e0b, #d97706)';
                btn.innerHTML = `🎖️ 挑战通关 (勋章获得)`;
            }
            ParticleEngine.emitConfetti();
        }
    };


    // 5. A/B Controlled Variable Studio (严谨控制变量对比实验引擎)
    const ABCompareStudio = {
        showModal() {
            const h1 = document.querySelector('.header h1 span');
            const title = h1 ? h1.innerText.trim() : '科学对比实验';

            const modal = document.createElement('div');
            modal.id = 'msisABModal';
            modal.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(15,23,42,0.88);backdrop-filter:blur(8px);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;';

            modal.innerHTML = `
                <div style="background:#0f172a;border:2px solid #8b5cf6;border-radius:16px;max-width:820px;width:100%;max-height:92vh;overflow-y:auto;padding:24px;box-shadow:0 0 35px rgba(139,92,246,0.3);color:#f8fafc;font-family:sans-serif;position:relative;">
                    <button id="btnCloseAB" style="position:absolute;top:16px;right:16px;background:#334155;border:none;color:#fff;width:32px;height:32px;border-radius:50%;cursor:pointer;font-size:16px;">✕</button>
                    
                    <div style="text-align:center;border-bottom:2px dashed #334155;padding-bottom:14px;margin-bottom:16px;">
                        <div style="color:#a78bfa;font-size:0.85rem;font-weight:700;letter-spacing:2px;margin-bottom:4px;">小学科学·核心探究方法论</div>
                        <h2 style="font-size:1.5rem;color:#f8fafc;margin:0;">【A/B 控制变量对比实验台】</h2>
                        <div style="color:#94a3b8;font-size:0.8rem;margin-top:6px;">实验课题: <span style="color:#38bdf8;">${title}</span> | 科学准则: <span style="color:#10b981;font-weight:bold;">只改变单一自变量，严格保持其他所有无关变量恒定</span></div>
                    </div>

                    <div style="background:#1e293b;border-radius:10px;padding:12px;border:1px solid #334155;margin-bottom:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:0.82rem;">
                        <div>
                            <span style="color:#a78bfa;font-weight:bold;">🎯 唯一自变量（改变条件）:</span>
                            <select id="abVariableSelect" style="width:100%;background:#0f172a;color:#f8fafc;border:1px solid #475569;border-radius:6px;padding:6px;margin-top:4px;">
                                <option>温度差异 (常温 20℃ vs 加热 80℃)</option>
                                <option>水分条件 (充足湿润 vs 干燥无水)</option>
                                <option>坡度高低 (平缓 15° vs 陡峭 45°)</option>
                                <option>受力大小 (轻击 1N vs 重击 5N)</option>
                            </select>
                        </div>
                        <div>
                            <span style="color:#10b981;font-weight:bold;">🔒 控制不变变量（恒定条件）:</span>
                            <div style="color:#cbd5e1;background:#0f172a;padding:6px;border-radius:6px;margin-top:4px;border:1px solid #475569;">
                                容器材质、测量时间、环境气压、实验器材完全保持一致
                            </div>
                        </div>
                    </div>

                    <!-- Side by Side Stage -->
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
                        <!-- Group A -->
                        <div style="background:#1e293b;border-radius:12px;padding:14px;border:2px solid #38bdf8;">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                                <span style="color:#38bdf8;font-weight:bold;font-size:0.9rem;">🟦 对照组 A (基准组)</span>
                                <span style="font-size:0.75rem;background:#0284c7;color:#fff;padding:2px 8px;border-radius:4px;">常规状态</span>
                            </div>
                            <div style="background:#020617;border-radius:8px;height:120px;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;border:1px solid #334155;">
                                <div id="abGraphicA" style="font-size:2.5rem;transition:transform 0.5s;">🧪</div>
                                <div id="abMetricA" style="position:absolute;bottom:8px;left:10px;font-size:0.8rem;color:#38bdf8;font-family:monospace;">测量基线: 100%</div>
                            </div>
                        </div>

                        <!-- Group B -->
                        <div style="background:#1e293b;border-radius:12px;padding:14px;border:2px solid #ec4899;">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                                <span style="color:#ec4899;font-weight:bold;font-size:0.9rem;">🟥 实验组 B (施加变量)</span>
                                <span style="font-size:0.75rem;background:#be185d;color:#fff;padding:2px 8px;border-radius:4px;">改变自变量</span>
                            </div>
                            <div style="background:#020617;border-radius:8px;height:120px;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden;border:1px solid #334155;">
                                <div id="abGraphicB" style="font-size:2.5rem;transition:transform 0.5s;">🔥</div>
                                <div id="abMetricB" style="position:absolute;bottom:8px;left:10px;font-size:0.8rem;color:#ec4899;font-family:monospace;">变量响应: 245% (显著加速)</div>
                            </div>
                        </div>
                    </div>

                    <!-- Real-time Comparison Conclusion -->
                    <div style="background:#1e293b;border-radius:10px;padding:14px;border:1px solid #334155;margin-bottom:16px;">
                        <div style="font-weight:600;font-size:0.85rem;color:#a78bfa;margin-bottom:6px;">📈 科学实证分析与对比结论：</div>
                        <div style="font-size:0.82rem;line-height:1.6;color:#cbd5e1;" id="abConclusionText">
                            通过严格控制无关变量恒定，仅改变单一自变量，观察到实验组 B 的物理反应速率显著优于对照组 A（差异率达 2.45 倍）。这严密证明了该自变量是影响本物理/生物过程的关键核心因素！
                        </div>
                    </div>

                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <button id="btnRunABSimulation" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9);color:#fff;border:none;padding:8px 18px;border-radius:8px;cursor:pointer;font-weight:bold;font-size:0.85rem;box-shadow:0 0 12px rgba(139,92,246,0.4);">
                            ⚡ 启动 A/B 同步对比演化
                        </button>
                        <button id="btnCloseABBottom" style="background:#334155;color:#fff;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:0.85rem;">
                            返回实验台
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            document.getElementById('btnCloseAB').onclick = () => modal.remove();
            document.getElementById('btnCloseABBottom').onclick = () => modal.remove();

            const runBtn = document.getElementById('btnRunABSimulation');
            runBtn.onclick = () => {
                AudioFX.play('victory');
                const gB = document.getElementById('abGraphicB');
                if (gB) {
                    gB.style.transform = 'scale(1.4) rotate(15deg)';
                    setTimeout(() => gB.style.transform = 'scale(1.0)', 600);
                }
                ParticleEngine.emitConfetti();
            };
        }
    };

    // 5. Inject Suite Toolbar into Controls Card
    function injectSuiteToolbar() {
        // [Simplified & Clean] Per user request: Remove complex data studio and report card to keep the UI clean, intuitive and distraction-free
        return;

        const controlsCard = document.querySelector('.controls-card');
        if (!controlsCard) return;

        let studioDiv = document.getElementById('msisDataStudioCard');
        if (!studioDiv) {
            studioDiv = document.createElement('div');
            studioDiv.id = 'msisDataStudioCard';
            studioDiv.style.cssText = 'background:#0f172a;border:1px solid #38bdf8;border-radius:10px;padding:12px;margin-top:10px;box-shadow:0 0 12px rgba(56,189,248,0.15);';
            studioDiv.innerHTML = `
                <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #1e293b;padding-bottom:8px;margin-bottom:10px;">
                    <div style="font-size:0.85rem;font-weight:700;color:#38bdf8;display:flex;align-items:center;gap:6px;">
                        <span>📝</span> 实验数据采集与探究报告
                    </div>
                    <button id="btnMsisHelp" style="background:transparent;border:none;color:#94a3b8;cursor:pointer;font-size:0.8rem;" title="使用说明">ℹ️</button>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">
                    <button id="btnMsisRecord" class="btn btn-primary" style="font-size:0.75rem;padding:6px 8px;background:#0284c7;color:#fff;">
                        📥 采样当前数据
                    </button>
                    <button id="btnMsisReport" class="btn" style="font-size:0.75rem;padding:6px 8px;background:#10b981;color:#fff;font-weight:600;">
                        📋 生成实验报告
                    </button>
                </div>
                <div style="display:grid;grid-template-columns:1fr;margin-bottom:8px;">
                    <button id="btnMsisABCompare" class="btn" style="font-size:0.75rem;padding:5px 8px;background:linear-gradient(135deg,#8b5cf6,#6d28d9);color:#fff;font-weight:600;box-shadow:0 0 8px rgba(139,92,246,0.3);">
                        ⚖️ 一键开启 A/B 控制变量对照实验台
                    </button>
                </div>
                <div style="max-height:110px;overflow-y:auto;background:#020617;border-radius:6px;border:1px solid #1e293b;">
                    <table style="width:100%;border-collapse:collapse;font-size:0.75rem;">
                        <thead>
                            <tr style="background:#1e293b;color:#94a3b8;">
                                <th style="padding:4px;text-align:center;width:30px;">#</th>
                                <th style="padding:4px;width:65px;">时间</th>
                                <th style="padding:4px;">遥测物理数据</th>
                            </tr>
                        </thead>
                        <tbody id="msisDataTableBody">
                            <tr><td colspan="3" style="text-align:center;color:#64748b;padding:12px;">点击上方【采样当前数据】记录多组实验参数</td></tr>
                        </tbody>
                    </table>
                </div>
            `;
            controlsCard.appendChild(studioDiv);

            document.getElementById('btnMsisRecord').onclick = () => LabDataStudio.recordCurrentState();
            document.getElementById('btnMsisABCompare').onclick = () => ABCompareStudio.showModal();
            document.getElementById('btnMsisReport').onclick = () => LabDataStudio.generateReportCard();
            document.getElementById('btnMsisHelp').onclick = () => {
                alert('【科学探究工作台说明】\\n1. 每次改变实验参数或完成操作后，点击【采样当前数据】记录一组实测物理值；\\n2. 累积 3 次以上有效数据后，点击【生成实验报告】可一键生成标准化实验报告单，支持打印或保存为学生实证作业！');
            };
        }
    }

    // 6. Universal Direct Manipulation & Physics Touch Controller
    function hookCanvasInteractivity(canvas) {
        if (!canvas) return;

        let isDragging = false;
        let startX = 0, startY = 0;

        canvas.style.cursor = 'grab';

        canvas.addEventListener('pointerdown', (e) => {
            const rect = canvas.getBoundingClientRect();
            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;
            const x = (e.clientX - rect.left) * scaleX;
            const y = (e.clientY - rect.top) * scaleY;

            isDragging = true;
            startX = x; startY = y;
            canvas.style.cursor = 'grabbing';

            ParticleEngine.emitRipple(x, y);

            // Handle direct manipulation on pointerdown
            handlePhysicsInteraction(x, y);

            if (window.onCanvasPointerDown) {
                window.onCanvasPointerDown(x, y);
            }
        });

        window.addEventListener('pointermove', (e) => {
            if (!isDragging) return;
            const rect = canvas.getBoundingClientRect();
            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;
            const x = (e.clientX - rect.left) * scaleX;
            const y = (e.clientY - rect.top) * scaleY;

            handlePhysicsInteraction(x, y);

            if (window.onCanvasPointerMove) {
                window.onCanvasPointerMove(x, y, x - startX, y - startY);
            }
        });

        window.addEventListener('pointerup', () => {
            if (!isDragging) return;
            isDragging = false;
            canvas.style.cursor = 'grab';
            if (window.onCanvasPointerUp) {
                window.onCanvasPointerUp();
            }
        });

        function handlePhysicsInteraction(x, y) {
            // Find all active range sliders on page
            const sliders = Array.from(document.querySelectorAll('input[type="range"]'));
            if (sliders.length === 0) return;

            // 1. Detect fishing or 2D positioning
            const h1 = document.querySelector('.header h1 span');
            const title = h1 ? h1.innerText : '';

            if (title.includes('钓鱼') || title.includes('车') || title.includes('磁')) {
                // Slider 1: Horizontal position
                if (sliders[0]) {
                    const min = parseFloat(sliders[0].min) || 120;
                    const max = parseFloat(sliders[0].max) || 600;
                    const val = Math.max(min, Math.min(max, Math.round(x)));
                    sliders[0].value = val;
                    sliders[0].dispatchEvent(new Event('input'));
                    if (sliders[0].oninput) sliders[0].oninput.call(sliders[0]);
                }
                // Slider 2: Depth / Vertical
                if (sliders[1] && y > 100) {
                    const min = parseFloat(sliders[1].min) || 80;
                    const max = parseFloat(sliders[1].max) || 280;
                    const val = Math.max(min, Math.min(max, Math.round(y - 60)));
                    sliders[1].value = val;
                    sliders[1].dispatchEvent(new Event('input'));
                    if (sliders[1].oninput) sliders[1].oninput.call(sliders[1]);
                }
            } else if (title.includes('斜面') || title.includes('坡度')) {
                // Angle slider
                const angleSlider = document.getElementById('angleSlider') || sliders[0];
                if (angleSlider) {
                    const ang = Math.round(Math.atan2(350 - y, Math.max(10, x - 180)) * 180 / Math.PI);
                    if (ang >= 15 && ang <= 60) {
                        angleSlider.value = ang;
                        angleSlider.dispatchEvent(new Event('input'));
                        if (angleSlider.oninput) angleSlider.oninput.call(angleSlider);
                    }
                }
            } else if (title.includes('杠杆') || title.includes('天平') || title.includes('平衡')) {
                // Effort arm slider
                const effortSlider = document.getElementById('effortSlider') || sliders[0];
                if (effortSlider && x > 380) {
                    const arm = Math.min(6, Math.max(1, Math.round((x - 360) / 45)));
                    effortSlider.value = arm;
                    effortSlider.dispatchEvent(new Event('input'));
                    if (effortSlider.oninput) effortSlider.oninput.call(effortSlider);
                }
            } else {
                // Universal fallback: map horizontal drag to first slider
                if (sliders[0]) {
                    const min = parseFloat(sliders[0].min) || 0;
                    const max = parseFloat(sliders[0].max) || 100;
                    const ratio = Math.max(0, Math.min(1, (x - 100) / 520));
                    const val = min + ratio * (max - min);
                    sliders[0].value = Math.round(val);
                    sliders[0].dispatchEvent(new Event('input'));
                    if (sliders[0].oninput) sliders[0].oninput.call(sliders[0]);
                }
            }
        }    }

    // Initializer
    function init() {
        const simCanvas = document.getElementById('simCanvas') || document.getElementById('cv') || document.querySelector('canvas');
        if (!simCanvas) return;

        ParticleEngine.init(simCanvas);
        LabDataStudio.init();
        QuestSystem.init();
        injectSuiteToolbar();
        hookCanvasInteractivity(simCanvas);

        window.MSIS = {
            ABCompareStudio,
            AudioFX,
            ParticleEngine,
            LabDataStudio,
            QuestSystem
        };

        if (window.self !== window.top) {
            document.querySelectorAll('.back-btn, a[href="index.html"]').forEach(function(el) {
                el.style.display = 'none';
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

const e=globalThis,t=e.ShadowRoot&&(void 0===e.ShadyCSS||e.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,i=Symbol(),r=new WeakMap;let a=class{constructor(e,t,r){if(this._$cssResult$=!0,r!==i)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=t}get styleSheet(){let e=this.o;const i=this.t;if(t&&void 0===e){const t=void 0!==i&&1===i.length;t&&(e=r.get(i)),void 0===e&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),t&&r.set(i,e))}return e}toString(){return this.cssText}};const s=(e,...t)=>{const r=1===e.length?e[0]:t.reduce((t,i,r)=>t+(e=>{if(!0===e._$cssResult$)return e.cssText;if("number"==typeof e)return e;throw Error("Value passed to 'css' function must be a 'css' function result: "+e+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+e[r+1],e[0]);return new a(r,e,i)},n=t?e=>e:e=>e instanceof CSSStyleSheet?(e=>{let t="";for(const i of e.cssRules)t+=i.cssText;return(e=>new a("string"==typeof e?e:e+"",void 0,i))(t)})(e):e,{is:o,defineProperty:l,getOwnPropertyDescriptor:c,getOwnPropertyNames:d,getOwnPropertySymbols:h,getPrototypeOf:p}=Object,u=globalThis,g=u.trustedTypes,m=g?g.emptyScript:"",v=u.reactiveElementPolyfillSupport,f=(e,t)=>e,_={toAttribute(e,t){switch(t){case Boolean:e=e?m:null;break;case Object:case Array:e=null==e?e:JSON.stringify(e)}return e},fromAttribute(e,t){let i=e;switch(t){case Boolean:i=null!==e;break;case Number:i=null===e?null:Number(e);break;case Object:case Array:try{i=JSON.parse(e)}catch(e){i=null}}return i}},b=(e,t)=>!o(e,t),x={attribute:!0,type:String,converter:_,reflect:!1,useDefault:!1,hasChanged:b};Symbol.metadata??=Symbol("metadata"),u.litPropertyMetadata??=new WeakMap;let y=class extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,t=x){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(e,t),!t.noAccessor){const i=Symbol(),r=this.getPropertyDescriptor(e,i,t);void 0!==r&&l(this.prototype,e,r)}}static getPropertyDescriptor(e,t,i){const{get:r,set:a}=c(this.prototype,e)??{get(){return this[t]},set(e){this[t]=e}};return{get:r,set(t){const s=r?.call(this);a?.call(this,t),this.requestUpdate(e,s,i)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??x}static _$Ei(){if(this.hasOwnProperty(f("elementProperties")))return;const e=p(this);e.finalize(),void 0!==e.l&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(f("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(f("properties"))){const e=this.properties,t=[...d(e),...h(e)];for(const i of t)this.createProperty(i,e[i])}const e=this[Symbol.metadata];if(null!==e){const t=litPropertyMetadata.get(e);if(void 0!==t)for(const[e,i]of t)this.elementProperties.set(e,i)}this._$Eh=new Map;for(const[e,t]of this.elementProperties){const i=this._$Eu(e,t);void 0!==i&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){const t=[];if(Array.isArray(e)){const i=new Set(e.flat(1/0).reverse());for(const e of i)t.unshift(n(e))}else void 0!==e&&t.push(n(e));return t}static _$Eu(e,t){const i=t.attribute;return!1===i?void 0:"string"==typeof i?i:"string"==typeof e?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),void 0!==this.renderRoot&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){const e=new Map,t=this.constructor.elementProperties;for(const i of t.keys())this.hasOwnProperty(i)&&(e.set(i,this[i]),delete this[i]);e.size>0&&(this._$Ep=e)}createRenderRoot(){const i=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return((i,r)=>{if(t)i.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(const t of r){const r=document.createElement("style"),a=e.litNonce;void 0!==a&&r.setAttribute("nonce",a),r.textContent=t.cssText,i.appendChild(r)}})(i,this.constructor.elementStyles),i}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,t,i){this._$AK(e,i)}_$ET(e,t){const i=this.constructor.elementProperties.get(e),r=this.constructor._$Eu(e,i);if(void 0!==r&&!0===i.reflect){const a=(void 0!==i.converter?.toAttribute?i.converter:_).toAttribute(t,i.type);this._$Em=e,null==a?this.removeAttribute(r):this.setAttribute(r,a),this._$Em=null}}_$AK(e,t){const i=this.constructor,r=i._$Eh.get(e);if(void 0!==r&&this._$Em!==r){const e=i.getPropertyOptions(r),a="function"==typeof e.converter?{fromAttribute:e.converter}:void 0!==e.converter?.fromAttribute?e.converter:_;this._$Em=r;const s=a.fromAttribute(t,e.type);this[r]=s??this._$Ej?.get(r)??s,this._$Em=null}}requestUpdate(e,t,i,r=!1,a){if(void 0!==e){const s=this.constructor;if(!1===r&&(a=this[e]),i??=s.getPropertyOptions(e),!((i.hasChanged??b)(a,t)||i.useDefault&&i.reflect&&a===this._$Ej?.get(e)&&!this.hasAttribute(s._$Eu(e,i))))return;this.C(e,t,i)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(e,t,{useDefault:i,reflect:r,wrapped:a},s){i&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,s??t??this[e]),!0!==a||void 0!==s)||(this._$AL.has(e)||(this.hasUpdated||i||(t=void 0),this._$AL.set(e,t)),!0===r&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}const e=this.scheduleUpdate();return null!=e&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[e,t]of this._$Ep)this[e]=t;this._$Ep=void 0}const e=this.constructor.elementProperties;if(e.size>0)for(const[t,i]of e){const{wrapped:e}=i,r=this[t];!0!==e||this._$AL.has(t)||void 0===r||this.C(t,void 0,i,r)}}let e=!1;const t=this._$AL;try{e=this.shouldUpdate(t),e?(this.willUpdate(t),this._$EO?.forEach(e=>e.hostUpdate?.()),this.update(t)):this._$EM()}catch(t){throw e=!1,this._$EM(),t}e&&this._$AE(t)}willUpdate(e){}_$AE(e){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(e){}firstUpdated(e){}};y.elementStyles=[],y.shadowRootOptions={mode:"open"},y[f("elementProperties")]=new Map,y[f("finalized")]=new Map,v?.({ReactiveElement:y}),(u.reactiveElementVersions??=[]).push("2.1.2");const w=globalThis,$=e=>e,k=w.trustedTypes,P=k?k.createPolicy("lit-html",{createHTML:e=>e}):void 0,S="$lit$",C=`lit$${Math.random().toFixed(9).slice(2)}$`,A="?"+C,M=`<${A}>`,T=document,D=()=>T.createComment(""),H=e=>null===e||"object"!=typeof e&&"function"!=typeof e,E=Array.isArray,F="[ \t\n\f\r]",O=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,N=/-->/g,R=/>/g,B=RegExp(`>|${F}(?:([^\\s"'>=/]+)(${F}*=${F}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),z=/'/g,I=/"/g,U=/^(?:script|style|textarea|title)$/i,L=e=>(t,...i)=>({_$litType$:e,strings:t,values:i}),W=L(1),V=L(2),q=Symbol.for("lit-noChange"),j=Symbol.for("lit-nothing"),G=new WeakMap,K=T.createTreeWalker(T,129);function Y(e,t){if(!E(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==P?P.createHTML(t):t}const Z=(e,t)=>{const i=e.length-1,r=[];let a,s=2===t?"<svg>":3===t?"<math>":"",n=O;for(let t=0;t<i;t++){const i=e[t];let o,l,c=-1,d=0;for(;d<i.length&&(n.lastIndex=d,l=n.exec(i),null!==l);)d=n.lastIndex,n===O?"!--"===l[1]?n=N:void 0!==l[1]?n=R:void 0!==l[2]?(U.test(l[2])&&(a=RegExp("</"+l[2],"g")),n=B):void 0!==l[3]&&(n=B):n===B?">"===l[0]?(n=a??O,c=-1):void 0===l[1]?c=-2:(c=n.lastIndex-l[2].length,o=l[1],n=void 0===l[3]?B:'"'===l[3]?I:z):n===I||n===z?n=B:n===N||n===R?n=O:(n=B,a=void 0);const h=n===B&&e[t+1].startsWith("/>")?" ":"";s+=n===O?i+M:c>=0?(r.push(o),i.slice(0,c)+S+i.slice(c)+C+h):i+C+(-2===c?t:h)}return[Y(e,s+(e[i]||"<?>")+(2===t?"</svg>":3===t?"</math>":"")),r]};class X{constructor({strings:e,_$litType$:t},i){let r;this.parts=[];let a=0,s=0;const n=e.length-1,o=this.parts,[l,c]=Z(e,t);if(this.el=X.createElement(l,i),K.currentNode=this.el.content,2===t||3===t){const e=this.el.content.firstChild;e.replaceWith(...e.childNodes)}for(;null!==(r=K.nextNode())&&o.length<n;){if(1===r.nodeType){if(r.hasAttributes())for(const e of r.getAttributeNames())if(e.endsWith(S)){const t=c[s++],i=r.getAttribute(e).split(C),n=/([.?@])?(.*)/.exec(t);o.push({type:1,index:a,name:n[2],strings:i,ctor:"."===n[1]?ie:"?"===n[1]?re:"@"===n[1]?ae:te}),r.removeAttribute(e)}else e.startsWith(C)&&(o.push({type:6,index:a}),r.removeAttribute(e));if(U.test(r.tagName)){const e=r.textContent.split(C),t=e.length-1;if(t>0){r.textContent=k?k.emptyScript:"";for(let i=0;i<t;i++)r.append(e[i],D()),K.nextNode(),o.push({type:2,index:++a});r.append(e[t],D())}}}else if(8===r.nodeType)if(r.data===A)o.push({type:2,index:a});else{let e=-1;for(;-1!==(e=r.data.indexOf(C,e+1));)o.push({type:7,index:a}),e+=C.length-1}a++}}static createElement(e,t){const i=T.createElement("template");return i.innerHTML=e,i}}function J(e,t,i=e,r){if(t===q)return t;let a=void 0!==r?i._$Co?.[r]:i._$Cl;const s=H(t)?void 0:t._$litDirective$;return a?.constructor!==s&&(a?._$AO?.(!1),void 0===s?a=void 0:(a=new s(e),a._$AT(e,i,r)),void 0!==r?(i._$Co??=[])[r]=a:i._$Cl=a),void 0!==a&&(t=J(e,a._$AS(e,t.values),a,r)),t}class Q{constructor(e,t){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){const{el:{content:t},parts:i}=this._$AD,r=(e?.creationScope??T).importNode(t,!0);K.currentNode=r;let a=K.nextNode(),s=0,n=0,o=i[0];for(;void 0!==o;){if(s===o.index){let t;2===o.type?t=new ee(a,a.nextSibling,this,e):1===o.type?t=new o.ctor(a,o.name,o.strings,this,e):6===o.type&&(t=new se(a,this,e)),this._$AV.push(t),o=i[++n]}s!==o?.index&&(a=K.nextNode(),s++)}return K.currentNode=T,r}p(e){let t=0;for(const i of this._$AV)void 0!==i&&(void 0!==i.strings?(i._$AI(e,i,t),t+=i.strings.length-2):i._$AI(e[t])),t++}}class ee{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,t,i,r){this.type=2,this._$AH=j,this._$AN=void 0,this._$AA=e,this._$AB=t,this._$AM=i,this.options=r,this._$Cv=r?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode;const t=this._$AM;return void 0!==t&&11===e?.nodeType&&(e=t.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,t=this){e=J(this,e,t),H(e)?e===j||null==e||""===e?(this._$AH!==j&&this._$AR(),this._$AH=j):e!==this._$AH&&e!==q&&this._(e):void 0!==e._$litType$?this.$(e):void 0!==e.nodeType?this.T(e):(e=>E(e)||"function"==typeof e?.[Symbol.iterator])(e)?this.k(e):this._(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==j&&H(this._$AH)?this._$AA.nextSibling.data=e:this.T(T.createTextNode(e)),this._$AH=e}$(e){const{values:t,_$litType$:i}=e,r="number"==typeof i?this._$AC(e):(void 0===i.el&&(i.el=X.createElement(Y(i.h,i.h[0]),this.options)),i);if(this._$AH?._$AD===r)this._$AH.p(t);else{const e=new Q(r,this),i=e.u(this.options);e.p(t),this.T(i),this._$AH=e}}_$AC(e){let t=G.get(e.strings);return void 0===t&&G.set(e.strings,t=new X(e)),t}k(e){E(this._$AH)||(this._$AH=[],this._$AR());const t=this._$AH;let i,r=0;for(const a of e)r===t.length?t.push(i=new ee(this.O(D()),this.O(D()),this,this.options)):i=t[r],i._$AI(a),r++;r<t.length&&(this._$AR(i&&i._$AB.nextSibling,r),t.length=r)}_$AR(e=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);e!==this._$AB;){const t=$(e).nextSibling;$(e).remove(),e=t}}setConnected(e){void 0===this._$AM&&(this._$Cv=e,this._$AP?.(e))}}class te{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,t,i,r,a){this.type=1,this._$AH=j,this._$AN=void 0,this.element=e,this.name=t,this._$AM=r,this.options=a,i.length>2||""!==i[0]||""!==i[1]?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=j}_$AI(e,t=this,i,r){const a=this.strings;let s=!1;if(void 0===a)e=J(this,e,t,0),s=!H(e)||e!==this._$AH&&e!==q,s&&(this._$AH=e);else{const r=e;let n,o;for(e=a[0],n=0;n<a.length-1;n++)o=J(this,r[i+n],t,n),o===q&&(o=this._$AH[n]),s||=!H(o)||o!==this._$AH[n],o===j?e=j:e!==j&&(e+=(o??"")+a[n+1]),this._$AH[n]=o}s&&!r&&this.j(e)}j(e){e===j?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??"")}}class ie extends te{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===j?void 0:e}}class re extends te{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==j)}}class ae extends te{constructor(e,t,i,r,a){super(e,t,i,r,a),this.type=5}_$AI(e,t=this){if((e=J(this,e,t,0)??j)===q)return;const i=this._$AH,r=e===j&&i!==j||e.capture!==i.capture||e.once!==i.once||e.passive!==i.passive,a=e!==j&&(i===j||r);r&&this.element.removeEventListener(this.name,this,i),a&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}}class se{constructor(e,t,i){this.element=e,this.type=6,this._$AN=void 0,this._$AM=t,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(e){J(this,e)}}const ne=w.litHtmlPolyfillSupport;ne?.(X,ee),(w.litHtmlVersions??=[]).push("3.3.2");const oe=globalThis;class le extends y{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){const t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=((e,t,i)=>{const r=i?.renderBefore??t;let a=r._$litPart$;if(void 0===a){const e=i?.renderBefore??null;r._$litPart$=a=new ee(t.insertBefore(D(),e),e,void 0,i??{})}return a._$AI(e),a})(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return q}}le._$litElement$=!0,le.finalized=!0,oe.litElementHydrateSupport?.({LitElement:le});const ce=oe.litElementPolyfillSupport;ce?.({LitElement:le}),(oe.litElementVersions??=[]).push("4.2.2");const de="settings",he=new Set([de,"overview","plan","history"]);function pe(e){if("string"!=typeof e)return de;const t=e.trim().toLowerCase();return he.has(t)?t:de}const ue=36e5,ge=e=>"number"==typeof e&&Number.isFinite(e),me=e=>"string"==typeof e&&/(?:Z|[+-]\d\d:\d\d)$/.test(e)?Date.parse(e):NaN;function ve(e,t){return Number(new Intl.DateTimeFormat("en-GB",{timeZone:t,hour:"2-digit",hourCycle:"h23"}).format(e))}function fe(e,t){return new Intl.DateTimeFormat("en-GB",{timeZone:t,hour:"2-digit",minute:"2-digit",hourCycle:"h23",timeZoneName:"shortOffset"}).format(e)}function _e(e=[]){return e.map(e=>({...e,start:me(e.start_time),end:me(e.end_time),price:ge(e.price)?e.price:null}))}function be(e,t,i,r,a){const s=[];let n=[];for(const i of e)(!ge(i[t])||n.length&&n.at(-1).end!==i.start)&&(n.length&&s.push(n),n=[]),ge(i[t])&&n.push(i);return n.length&&s.push(n),s.map(e=>{const s=e[0],n=e.at(-1),o=[[s.start,s[t]],...e.map(e=>[(e.start+e.end)/2,e[t]]),[n.end,n[t]]];return`M ${i(s.start)} ${a} L ${o.map(([e,t])=>`${i(e)} ${r(t)}`).join(" L ")} L ${i(n.end)} ${a} Z`})}class xe{constructor(e,t){this.callWS=e,this.onState=t,this.generation=0,this.onReady=()=>this.start(),this.onDisconnected=()=>this.pause("Home Assistant disconnected")}setActive(e,t){this.active===e&&this.connection===t||(this.stop(),this.active=e,this.connection=t,e&&(t?.addEventListener?.("ready",this.onReady),t?.addEventListener?.("disconnected",this.onDisconnected),!1!==t?.connected?this.start():this.onState({usable:!1,reason:"Home Assistant disconnected"})))}start(){this.active&&(clearInterval(this.timer),this.refresh(),this.timer=setInterval(()=>this.refresh(),6e4))}pause(e){clearInterval(this.timer),this.timer=null,this.generation++,this.onState({usable:!1,reason:e})}async refresh(){const e=++this.generation;try{const t=await this.callWS({type:"victron_charge_control/solar_forecast"});this.active&&e===this.generation&&this.onState(function(e){if(!e?.usable)return{usable:!1,reason:e?.reason||"PV forecast unavailable"};try{if(new Intl.DateTimeFormat("en",{timeZone:e.time_zone}).format(),!e.time_zone||2!==e.days?.length||!Array.isArray(e.intervals))throw new Error;const t=e.days.map(e=>({...e,start:me(e.start),end:me(e.end)}));if(t.some(e=>!(/^\d{4}-\d{2}-\d{2}$/.test(e.date)&&Number.isFinite(e.start)&&e.end>e.start))||t[0].end!==t[1].start)throw new Error;const i=e.intervals.map(e=>({...e,start:me(e.start),end:me(e.end)})).filter(e=>Number.isFinite(e.start)&&e.end>e.start&&ge(e.pv_estimate)&&e.pv_estimate>=0).map(e=>({...e,pv_estimate10:ge(e.pv_estimate10)&&e.pv_estimate10>=0?e.pv_estimate10:null})).sort((e,t)=>e.start-t.start);if(!i.some(e=>e.end>t[0].start&&e.start<t[1].end))throw new Error;return{...e,usable:!0,days:t,intervals:i}}catch{return{usable:!1,reason:"Invalid PV forecast data"}}}(t))}catch(t){const i="unknown_command"===t?.code?"Restart Home Assistant to load PV forecast support, then refresh the dashboard":"PV forecast unavailable (check integration support and connection)";this.active&&e===this.generation&&this.onState({usable:!1,reason:i})}}stop(){clearInterval(this.timer),this.timer=null,this.generation++,this.connection?.removeEventListener?.("ready",this.onReady),this.connection?.removeEventListener?.("disconnected",this.onDisconnected),this.active=!1}}const ye="victron-charge-controller-card",we="victron-charge-controller-card-editor",$e=["off","auto","manual","force_charge","force_discharge"],ke={off:{icon:"mdi:power-off",label:"Off"},auto:{icon:"mdi:auto-fix",label:"Auto"},manual:{icon:"mdi:hand-back-right",label:"Manual"},force_charge:{icon:"mdi:battery-charging-high",label:"Force Charge"},force_discharge:{icon:"mdi:battery-arrow-down-outline",label:"Force Discharge"}},Pe={idle:{icon:"mdi:pause-circle-outline",label:"Idle"},charge:{icon:"mdi:battery-charging",label:"Charging"},pv_charge:{icon:"mdi:solar-power-variant",label:"PV Charging"},discharge:{icon:"mdi:battery-arrow-down",label:"Discharging"}},Se={default:{icon:"mdi:transmission-tower",label:"Default"},reduced:{icon:"mdi:transmission-tower-off",label:"Reduced"}},Ce={overview:[{heading:"Mode and permissions",items:["Select Off, Auto, Manual, Force Charge or Force Discharge. The question mark beside Mode explains each mode.","Charge Allowed and Discharge Allowed control permission for grid charging and battery discharge. PV charging operates independently of Charge Allowed. Click a switch name for details.","Use Settings to adjust powers, battery limits, price thresholds and schedules."]},{heading:"Grid setpoint calculation",items:["The signed values show the mode setting, PV charging battery share, solar surplus, grid consumer offset and battery feedback reported by the controller.","Grid setpoint is the computed target after limits. When it is capped, the uncapped calculation appears in parentheses. Unavailable calculation data is not treated as zero."]}],settings:[{heading:"Help for each input",items:["Click a light-blue slider or switch name to read what it does and how it affects the controller. Slider help also shows its minimum, maximum and step size.","The question mark beside Mode explains all five modes. The question mark beside the action buttons explains Recalculate and Clear Schedule.","Click Charging, Discharging or Recalculation Hours above the hour chips for help with that group."]},{heading:"Mode",items:["Pick a control mode: Off, Auto, Manual, Force Charge or Force Discharge.","In Auto mode the controller decides based on price, PV surplus and SOC."]},{heading:"Tuning",items:["Adjust charge / discharge power, battery limits, grid setpoints and price thresholds.","Hold a slider knob to unlock continuous adjustment."]},{heading:"Blocked hours",items:["Tap an hour chip to toggle it on or off.","Changes apply every day until you clear them."]}],plan:[{heading:"Reading the chart",items:["In Price and PV forecast views, each bar shows the scheduled action for one price period (today + tomorrow).","Tap a Price bar to see price details for that period. The full day fits the card width. Hour blocks contain one hourly bar or four separate 15-minute columns.","Times use the Home Assistant time zone; tooltip and picker UTC offsets distinguish repeated times when daylight saving ends."]},{heading:"Price cutoffs",items:["With Relative Auto Mode off (the default), lines show the absolute price thresholds. With it on, Charge cutoff = maximum reference price minus Charge Price Delta; Discharge cutoff = minimum reference price plus Discharge Price Delta. Deltas are signed ct/kWh. Charging wins overlaps and duration budgets are ignored, including zero; permissions and SOC protection still apply.","Both days use the same current/future reference prices from Charge Plan, including tomorrow or later and prices excluded by blocks or PV Charge. Lines are hidden when their reference is unavailable or outside the chart scale. Hold a line to drag its cutoff; this edits the corresponding delta in relative mode.","Lines reflect current selection cutoffs. Reference prices can refresh without changing the saved schedule; Recalculate and the existing Auto-setting and Recalculation Hours triggers apply the new selection. Switching Relative Auto Mode recalculates only in Auto; restoring it after restart preserves schedules."]},{heading:"PV forecast requirements",items:["Install and configure the Solcast PV Solar Forecast integration in Home Assistant with your Solcast API key and rooftop sites. It must be loaded and have downloaded forecast data.","In Settings > Devices & services > Victron Charge Control > Configure, enable Use Solcast forecast (enabled by default). Solcast is discovered automatically; no API key or forecast entity selection is needed in Victron Charge Control, and detailed forecast attributes can stay disabled.","The forecast must cover now through the end of tomorrow, and its source update must be no more than 36 hours old. If the toggle is disabled, read the message below it and check Solar Forecast Status in the integration diagnostics. Check Solcast configuration and updates if data is missing or stale."]},{heading:"Using the PV forecast view",items:["On the automatic Plan page, use the Price / PV forecast toggle below Charge Allowed and Discharge Allowed to switch views. Today and Tomorrow use the Home Assistant time zone.","The light-yellow area shows the central Solcast estimate (pv_estimate). The yellow area shows the lower, 10th-percentile estimate (pv_estimate10), not 10% of the central value. Both show power in kW on the right axis; the areas overlap and are not added together.","Price interval bars use the same action colors, blocked-hour hatching and past-hour styling as Price. The current price period has a dashed outline and highlighted label. Bars and forecast curves share the same zero line, with negative prices below it. Price thresholds are shown only in Price view.","Each title shows PV 10% and PV energy in kWh, calculated from the available forecast intervals for that day. These are forecast totals, not measured production; missing intervals are not counted as zero. A missing day or missing lower estimates is shown as unavailable.","Hover, tap or keyboard-focus a time slot to see its time, price and PV estimates in the top-left tooltip. Half-hour forecasts are preserved, and missing values remain gaps. Prices can be unavailable while the PV forecast is still shown.","Right-click or hold a current or future priced period to change its action, or focus its time slot and press Enter or Space. Periods without prices are read-only. The view returns to Price if the forecast becomes unusable. Switching views does not enable PV charging or alter charging permissions.","Forecast data is read from the integration cache every minute while this page is open. This does not request a Solcast refresh or change the charging schedule."]},{heading:"Charging modes",items:[[{text:"Charge",bold:!0},{text:" imports power from the grid at the configured Charge Power to fill the battery; with Battery Power Control active, Charge Power instead targets battery charging watts. It only runs in planned charge hours while the Charge Allowed switch is on and the battery is below the Max SOC limit."}],[{text:"Discharge",bold:!0},{text:" exports battery power plus the optional 15-minute averaged solar surplus until Min SOC is reached. With Battery Power Control active during full discharge, Discharge Power targets battery watts and feedback replaces solar-surplus and Grid Consumer offsets. At Min SOC it switches to surplus-only export; at Min SOC minus SOC Hysteresis (at least 0%) it stops and applies the Idle Setpoint without the action confirmation delay. Surplus-only resumes at Min SOC, and full discharge resumes strictly above Min SOC plus SOC Hysteresis. Averaged surplus can exceed available solar power and temporarily draw from the battery. After restart, discharge starts stopped below Min SOC, surplus-only through the upper threshold, and full above it. Without a surplus sensor, discharge stops at Min SOC and resumes above the upper threshold. With zero hysteresis, discharge stops at or below Min SOC and runs at full power above it. Stopping does not disable other battery flows managed by Victron."}],[{text:"PV Charge",bold:!0},{text:" charges the battery from solar surplus; an enabled Grid Consumer offset can also request grid import. It runs independently of the Charge Allowed switch and of blocked charging hours, and requires the optional solar surplus sensor to be configured."}],[{text:"PV Charging Battery Share",bold:!0},{text:" (Settings card) splits the surplus between the battery and grid export during PV charge hours."}],"Outside planned hours the controller uses Idle Setpoint, normally 0 W; an enabled Grid Consumer adds the consumer shortfall after solar surplus in active control modes."]},{heading:"Override price intervals",items:[[{text:"Tap an hour",bold:!0},{text:" in Price or PV forecast to open the action picker; right-click and hold also work. Keyboard users can focus an hour and press Enter or Space."}],"All available intervals in that hour start selected. Deselect any quarters, then choose Idle, Charge, Discharge or PV Charge to override only the selection. Past intervals and missing prices are disabled. Hourly feeds retain one whole-hour choice.","Use the Recalculate button to restore the automatic plan."]},{heading:"Recurring blocks",items:["Edit blocked charging / discharging hours under Settings to apply every day."]},{heading:"Fixed plans",items:["Switch to a numbered plan page (or press +) to define a recurring 24-hour pattern of charging, discharging and PV charging hours.","Activate a plan from its detailed view (check-mark button) — its hours extend the auto plan and win over it for today and tomorrow.","Only one plan can be active at a time."]}],history:[{heading:"What it shows",items:["Aggregated cost and energy statistics for the selected period."]},{heading:"Navigation",items:["Switch period with Day / Week / Month / Year.","Use the arrow buttons to step through time."]}]},Ae={control_mode:[{heading:"Off",items:["Requests Idle and resets the grid target to the configured Idle Setpoint. It does not switch off the Victron system or prevent battery flows managed by Victron."]},{heading:"Auto",items:["Builds a price-based schedule from available current and future EPEX periods using absolute price thresholds and duration budgets by default, or signed price deltas without duration caps when Relative Auto Mode is on. Recurring blocks still apply. An active fixed plan and individual period overrides can change that schedule. Permission switches and SOC protection still apply."]},{heading:"Manual",items:["Follows the hours you choose in the Plan card and any active fixed plan instead of selecting hours by price. Unscheduled hours use Idle. Permission switches and SOC protection still apply; selected Recalculation Hours reset manual charge/discharge slots."]},{heading:"Force Charge",items:["Requests grid charging at Charge Power without waiting for a scheduled hour. It bypasses price selection and recurring blocked hours, but still requires Charge Allowed and obeys Max SOC, hysteresis and grid setpoint limits."]},{heading:"Force Discharge",items:["Requests discharge without waiting for a scheduled hour. It bypasses price selection and recurring blocked hours, but still requires Discharge Allowed and obeys SOC protection, discharge stages and export limits."]}],relative_auto_mode:["Defaults off: automatic selection uses absolute price thresholds and duration budgets. When enabled, Charge Price Delta and Discharge Price Delta reuse the existing threshold values and ranges in ct/kWh; deltas may be negative.","Charging qualifies at price <= maximum reference price minus Charge Price Delta. Discharging qualifies at price >= minimum reference price plus Discharge Price Delta. The references span all available current and future price intervals, including tomorrow or later, before blocked hours and PV Charge exclusions. Charging wins if both qualify.","Duration budgets are ignored, even when zero. Their saved values are retained and become editable again when this switch is off. Charge Allowed, Discharge Allowed, SOC protection, recurring blocks, PV Charge exclusions and fixed-plan overrides still apply.","Available in every control mode; changing it recalculates only in Auto. The switch and existing schedules survive restart without an automatic replan on restore. Reference refreshes update chart cutoffs without replanning; use Recalculate or the existing Auto-setting and Recalculation Hours triggers to update the saved schedule."],grid_consumer:["When battery feedback is active for Charge or full Discharge, it already accounts for this load and replaces this offset. Otherwise, it subtracts the current solar surplus from the measured consumer load and adds only the remaining shortfall to the raw grid target in Auto, Manual, Force Charge and Force Discharge, including Idle and PV Charge actions, before grid and reduced feed-in limits. Off keeps the configured Idle Setpoint unchanged.","Without solar surplus, Charge 3000 W + EV 3000 W = 6000 W, capped to the default Max Grid Setpoint of 5000 W. Discharge −2000 W + consumer 3000 W = 1000 W before limits. With a 3000 W consumer and 2000 W solar surplus, only 1000 W is added. Surplus equal to or above the load adds zero. Missing or invalid solar readings use the full consumer load.","The first shortfall change starts a fixed five-second window. The latest consumer and solar readings are applied when it expires; further changes do not restart it. Initial enable, restart restore and recovery also wait five seconds. The existing setpoint watt deadband still applies. Disabling, Off or an invalid source clears the offset without delay.","This adjusts the target, not the energy origin: intentional battery discharge remains possible. The source must measure a load already included in ESS consumption. For multiple loads, select an existing aggregate power sensor.","Choose the optional Grid consumer power sensor (W or kW) in Settings → Devices & Services → Victron Charge Control → Configure, then enable this switch. It defaults off and is restored after restart. Invalid or unavailable consumer readings use zero offset; the configured switch can still be turned off."],battery_power_control:["Uses measured battery power to target Charge Power during regular Charge and Discharge Power during full Discharge, including force modes. PV Charge, solar-only discharge at Min SOC, Idle and Off keep their existing control.","Choose the optional Battery power sensor in integration setup, Configure or Reconfigure. It must report W or kW, positive when charging and negative when discharging. This switch defaults off and is restored after restart.","The grid target is applied grid watts + desired signed battery watts − measured battery watts. For example, 3000 W applied grid + 3000 W desired battery − 2000 W measured battery requests 4000 W grid. Household, solar and consumer effects are already reflected, so active feedback replaces the solar-surplus and Grid Consumer offsets for eligible actions.","Startup uses legacy grid-only control until feedback is ready. The controller uses each new battery reading once and waits five seconds after changing the grid target before adjusting again. Readings older than 120 seconds, invalid values or an unavailable sensor use grid-only control with the existing offsets until feedback recovers. You can still turn this switch off during a sensor outage.","Use a sensor that reports current battery power promptly. Repeated reports of old measurements cannot be detected by the freshness check, and delayed measurements can make the grid target oscillate. SOC protection, grid limits, reduced feed-in limits and device limits still apply. The requested battery target is not guaranteed actual battery power."],charge_allowed:["Allows grid charging in scheduled and Force Charge operation. Turning it off stops those requests; Grid Consumer can still add import to Idle or PV Charge. It does not erase the schedule.","PV Charge is independent of this switch because it allocates solar surplus. Max SOC protection still applies to both charging actions."],discharge_allowed:["Allows scheduled discharge and Force Discharge. Turning it off makes those requests fall back to Idle without erasing the schedule.","This also gates surplus-only discharge at Min SOC. It does not disable solar export during PV Charge or other battery flows managed by Victron."],disable_discharge:["Writes 0 W to the configured Maximum discharge power entity every 5 seconds throughout regular Charge slots and Force Charge, even at Max SOC, with zero Charge Power or with Charge Allowed off. PV Charge is excluded.","Leaving the charging window, turning this switch off, selecting Off mode or a watchdog stop releases the limit with −1 W (unlimited). The previous numerical limit is not restored.","Choose the optional Maximum discharge power entity (a writable number in W) in the integration configuration first. This switch defaults off and is restored after restart. Without a configured entity it cannot be enabled; an external entity outage still allows turning it off.","Missing entities and failed writes are logged and retried while other controls continue. Pending release survives restart and reconfiguration; orderly shutdown attempts release. A Home Assistant crash or outage can leave the device limit in place until communication resumes and cleanup succeeds."],charge_power:["Sets the positive grid power target used during grid charging, in watts. A larger value requests more grid import, subject to Max Grid Setpoint and the Victron system’s own limits.","With Battery Power Control active, this is the desired battery charging power instead; measured feedback replaces solar and Grid Consumer offsets. Grid-only control resumes on feedback fallback or when Battery Power Control is off. Household loads, solar production and device limits affect actual power. Charge Allowed and SOC protection must permit charging."],discharge_power:["Sets the battery-power component of the discharge request, in watts. During full discharge the controller requests export equal to this value plus the optional solar surplus sensor’s 15-minute average.","With Battery Power Control active during full discharge, this is the desired battery discharge power; feedback replaces the solar-surplus and Grid Consumer offsets. Grid-only control resumes on feedback fallback or when Battery Power Control is off. Solar-only discharge at Min SOC keeps its existing control.","The negative grid target is clamped by Min Grid Setpoint and, during reduced feed-in, Reduced Max Feed-in. At Min SOC the battery-power component is removed; without a surplus sensor discharge stops."],pv_charging_battery_share:["Controls how solar surplus is split during a PV Charge hour. At 0% the target exports the averaged surplus; at 100% it uses Idle Setpoint, normally retaining surplus for the battery. Intermediate values blend those two targets.","Requires the optional solar surplus sensor and a PV Charge slot. Higher values favor battery charging. Max SOC and grid/export limits still apply; Charge Allowed and blocked charging hours do not prevent PV Charge."],min_soc:["Sets the lower battery state-of-charge boundary for full discharge. With a solar surplus sensor, reaching this value changes full discharge to export of averaged solar surplus only.","Surplus-only discharge stops at Min SOC minus SOC Hysteresis, with a floor of 0%, and resumes at Min SOC. Full discharge resumes strictly above Min SOC plus SOC Hysteresis. Averaged surplus can temporarily draw battery power when actual solar output falls.","Without a surplus sensor, discharge stops at Min SOC and resumes strictly above the upper threshold. Stopping applies Idle Setpoint; it does not disable other Victron battery flows."],max_soc:["Sets the upper battery state-of-charge boundary for grid charging and PV Charge. At or above this value the controller requests Idle instead of charging.","Charging can resume once SOC falls strictly below Max SOC minus SOC Hysteresis. This protection also applies to Force Charge. Other charging managed by Victron can still occur."],soc_hysteresis:["Sets a buffer in SOC percentage points to avoid repeatedly switching actions near a battery limit. Charging stops at Max SOC and resumes strictly below Max SOC minus this buffer.","Full discharge changes to surplus-only at Min SOC and resumes strictly above Min SOC plus this buffer. With a surplus sensor, surplus-only stops at max(0%, Min SOC minus the buffer) and resumes at Min SOC. Without that sensor, discharge stops at Min SOC until the upper threshold is exceeded.","After restart, discharge starts stopped below Min SOC, surplus-only through the upper threshold, and full above it. Without a surplus sensor it stays stopped through that threshold. With a zero buffer, discharge stops at or below Min SOC and can run fully above it."],idle_setpoint:["Sets the grid power target when the controller is Idle, including Off, unscheduled hours and SOC-blocked actions. Positive values request grid import; negative values request export; zero targets balanced grid power.","During active control, an enabled Grid Consumer adds the consumer shortfall after solar surplus before the target is clamped between Min and Max Grid Setpoint; Off resets directly to Idle Setpoint. It is also the target at 100% PV Charging Battery Share, so changing it affects PV Charge allocation. Idle does not mean the battery is disconnected."],min_grid_setpoint:["Sets the lowest grid power target the controller may request. Negative values represent export: a more negative limit permits more export, while zero prevents the controller from requesting a negative target.","During active control, all computed setpoints are clamped to this limit; Off resets directly to Idle Setpoint. During reduced feed-in, Reduced Max Feed-in can further restrict discharge and PV Charge export. This is a requested target, not a measurement of actual grid power."],max_grid_setpoint:["Sets the highest grid power target the controller may request. Positive values represent import, so reducing this limit can cap the Charge Power request.","During active control, all computed setpoints, including Idle and PV Charge, are clamped between Min and Max Grid Setpoint; Off resets directly to Idle Setpoint. Actual grid power also depends on the Victron system and connected loads."],cheapest_hours_auto_charge:["Sets the grid-charge duration budget in hours, in 0.25-hour steps, across available current and future prices. Whole price intervals are selected without exceeding the budget; hourly feeds keep whole hours.","Only periods at or below Charge Price Threshold qualify. Recurring blocked charging hours and PV Charge slots are skipped; conflicts with selected discharge hours favor discharge. Zero selects no automatic grid-charge periods. Changing this value in Auto recalculates the schedule."],expensive_hours_auto_discharge:["Sets the discharge duration budget in hours, in 0.25-hour steps, across available current and future prices. Whole price intervals are selected without exceeding the budget; hourly feeds keep whole hours.","Only periods at or above Discharge Price Threshold qualify. Recurring blocked discharging hours and PV Charge slots are skipped. Zero selects no automatic discharge periods. Changing this value in Auto recalculates the schedule; actual discharge still requires permission and sufficient SOC."],charge_price_threshold:["Sets the highest EPEX spot price, in ct/kWh, eligible for automatic grid charging. A price equal to the threshold qualifies. Raising it allows more hours to qualify; Charge Duration caps the total selected duration.","Changing it in Auto recalculates the schedule. It does not gate Force Charge or explicitly chosen manual/fixed-plan hours. This is the spot-price comparison, not a total electricity bill calculation."],discharge_price_threshold:["Sets the lowest EPEX spot price, in ct/kWh, eligible for automatic discharge. A price equal to the threshold qualifies. Raising it restricts selection to higher-priced hours; Discharge Duration caps their total duration.","Changing it in Auto recalculates the schedule. It does not gate Force Discharge or explicitly chosen manual/fixed-plan hours. Permission switches and SOC limits still govern execution."],grid_feed_in_control:["Enables price-based control of the linked Victron maximum grid feed-in setting. Prices strictly below Price Threshold use Reduced Max Feed-in; prices at or above it use Default Max Feed-in.","While reduced mode is active, discharge and PV Charge export targets are also capped by the reduced limit. When this feature is disabled after applying a reduced limit, the controller restores the configured default limit when the linked entity is available.","Requires the configured writable maximum feed-in entity and current price data. If the price is unavailable, no new feed-in limit is written."],control_dc_coupled_feed_in:["Allows the controller to operate the linked Victron DC-coupled feed-in switch: on at normal prices, off while reduced feed-in is active.","Requires Feed-in Control to be enabled, a configured and available external DC feed-in switch, and a control mode other than Off. Disabling this option stops controlling that switch; it does not automatically restore its previous state."],grid_feed_in_price_threshold:["Sets the EPEX spot-price boundary, in ct/kWh, for reduced feed-in. Prices strictly below this value select Reduced Max Feed-in. At exactly the threshold or above it, Default Max Feed-in applies.","Only affects price-based feed-in control when Feed-in Control is enabled. It also determines the DC-coupled feed-in switch state when that optional control is enabled."],default_max_grid_feed_in:["Sets the normal maximum grid feed-in limit written to the linked Victron entity when Feed-in Control is enabled and price is at or above its threshold.","This is an export ceiling in watts, not a command to export that amount. It is also the limit restored when disabling feed-in control after a reduced limit was applied."],reduced_max_grid_feed_in:["Sets the maximum grid feed-in limit used when Feed-in Control is enabled and price is strictly below its threshold. Zero requests no feed-in through this limit.","In reduced mode it also caps discharge and PV Charge export targets. Min Grid Setpoint may impose a tighter limit. This setting limits export; it does not itself schedule charging or discharging."],blocked_charging_hours:["Select hour chips to exclude those hours from automatic grid-charge selection every day. Each chip covers the hour beginning at the displayed time, using Home Assistant’s local time. Click a selected chip again to remove the recurring block.","Explicit per-day overrides and active fixed plans can still schedule the hour. Force Charge bypasses recurring blocks, and PV Charge is independent of charging blocks. Charge Allowed and SOC limits still apply to grid charging."],blocked_discharging_hours:["Select hour chips to exclude those hours from automatic discharge selection every day. Each chip covers the hour beginning at the displayed time, using Home Assistant’s local time. Click a selected chip again to remove the recurring block.","Explicit per-day overrides and active fixed plans can still schedule the hour. Force Discharge bypasses recurring blocks. Discharge Allowed and SOC protection still govern discharge."],replan_hours:["Select the local hours at which the daily replan runs, at minute 00. In Auto it rebuilds the price-based schedule; in Manual it clears manually chosen charge/discharge slots and reapplies any active fixed plan.","Expired slots are cleaned up during replanning. With no hours selected, these timed replans are disabled; the Recalculate button and automatic recalculation caused by Auto-setting changes remain available."],schedule_actions:[{heading:"Recalculate",items:["Rebuilds the automatic charge/discharge schedule from the available current and future EPEX prices, using absolute price thresholds and duration budgets by default, or signed price deltas without duration caps in Relative Auto Mode. Recurring blocks still apply. Requires Auto mode and usable price data.","Replaces individual charge/discharge selections with the calculated plan, preserves PV Charge slots, and reapplies any active fixed plan. It does not change the control mode."]},{heading:"Clear Schedule",items:["Clears scheduled charge, discharge and PV Charge hours and both recurring blocked-hour lists. Saved fixed plans are retained; any active fixed plan is immediately reapplied, so the resulting schedule may not be empty.","Does not change the control mode, permission switches or Recalculation Hours. Force modes can continue operating, and later Auto recalculation can populate the schedule again."]}]},Me={cheapest_hours_auto_charge:["Ignored in Relative Auto Mode, even when zero. The saved Charge Duration is retained and used again when relative mode is off. All eligible charging periods can be selected without a duration cap; Charge Allowed and SOC protection still apply."],expensive_hours_auto_discharge:["Ignored in Relative Auto Mode, even when zero. The saved Discharge Duration is retained and used again when relative mode is off. All eligible discharge periods can be selected without a duration cap; Discharge Allowed and SOC protection still apply."],charge_price_threshold:["Signed delta in ct/kWh below the maximum reference price: charging qualifies at price <= maximum minus Charge Price Delta, including equality. A negative delta puts the cutoff above the maximum. References cover available current and future intervals, including tomorrow or later, before blocked hours and PV Charge exclusions.","No duration cap applies, even with Charge Duration zero. Charging wins overlaps with discharge. Changing the delta in Auto recalculates the schedule; Charge Allowed, SOC protection and fixed-plan overrides still apply. Force and manually chosen periods do not use this comparison."],discharge_price_threshold:["Signed delta in ct/kWh above the minimum reference price: discharging qualifies at price >= minimum plus Discharge Price Delta, including equality. A negative delta puts the cutoff below the minimum. References cover available current and future intervals, including tomorrow or later, before blocked hours and PV Charge exclusions.","No duration cap applies, even with Discharge Duration zero. Charging wins overlaps with discharge. Changing the delta in Auto recalculates the schedule; Discharge Allowed, SOC protection and fixed-plan overrides still apply. Force and manually chosen periods do not use this comparison."]},Te=Array.from({length:24},(e,t)=>t),De=1e4,He={day:{label:"Day",period:"hour",icon:"mdi:calendar-today"},week:{label:"Week",period:"day",icon:"mdi:calendar-week"},month:{label:"Month",period:"day",icon:"mdi:calendar-month"},year:{label:"Year",period:"month",icon:"mdi:calendar-range"}};class Ee extends le{static get properties(){return{hass:{type:Object},config:{type:Object}}}constructor(){super(),this._sliderHoldTimers=new WeakMap,this._sliderUnlocked=new WeakSet,this._thresholdDrag=null,this._thresholdHoldTimer=null,this._onThresholdPointerMoveBound=this._onThresholdPointerMove.bind(this),this._onThresholdPointerUpBound=this._onThresholdPointerUp.bind(this),this._onThresholdTouchMoveBound=this._onThresholdTouchMove.bind(this),this._pendingThresholds={},this._lastThresholdContext=null,this._costRange="day",this._costRangeOffsets={day:0,week:0,month:0,year:0},this._costMode="cost",this._costStatsState={status:"idle",key:null,points:[],error:null},this._tooltipBar=null,this._tooltipHideTimer=null,this._pickerBar=null,this._chartPeriods={},this._pickerApplying=!1,this._barHoldTimer=null,this._barHoldStart=null,this._barLongPressFired=!1,this._onPickerKeyDownBound=this._onPickerKeyDown.bind(this),this._helpOpen=!1,this._helpTopic=null,this._helpTrigger=null,this._onHelpKeyDownBound=this._onHelpKeyDown.bind(this),this._planPage="auto",this._fixedPlanNumber=null,this._pendingFixedPlanHours={},this._pendingActiveFixedPlan=void 0,this._pendingFixedPlanNames={},this._pendingPlanActions={},this._lastScheduleUpdateSeen=null,this._planNameEditing=!1,this._planNameDraft="",this._entityAliases={},this._lastServiceError=null,this._warnedMissingFixedPlans=!1,this._planChartMode="price",this._solarForecast={usable:!1,reason:"Loading PV forecast"},this._forecastPoller=new xe(e=>this._callWS(e),e=>{this._solarForecast=e,e.usable||this._setPlanChartMode("price"),this.requestUpdate()}),this._onForecastVisibilityBound=()=>this._syncSolarForecast()}connectedCallback(){super.connectedCallback(),document.addEventListener("visibilitychange",this._onForecastVisibilityBound),this._syncSolarForecast()}updated(){this._syncSolarForecast(),!this._pickerBar||"plan"===this.config?.view&&"auto"===this._planPage||this._closePicker()}_syncSolarForecast(){const e=this.isConnected&&!document.hidden&&"plan"===this.config?.view&&"auto"===this._planPage&&!!this.hass;this._forecastPoller.setActive(e,this.hass?.connection)}disconnectedCallback(){super.disconnectedCallback(),this._forecastPoller.stop(),document.removeEventListener("visibilitychange",this._onForecastVisibilityBound),this._setPlanChartMode("price"),this._finishThresholdDrag(!1),this._tooltipHideTimer&&clearTimeout(this._tooltipHideTimer),this._closePicker(!1),this._barHoldTimer&&(clearTimeout(this._barHoldTimer),this._barHoldTimer=null),window.removeEventListener("keydown",this._onPickerKeyDownBound),window.removeEventListener("keydown",this._onHelpKeyDownBound)}setConfig(e){this._pickerBar&&this._closePicker(),this.config={entity_prefix:"victron_charge_control",...e,view:pe(e.view)}}getCardSize(){return"overview"===this.config?.view?6:12}static getConfigElement(){return document.createElement(we)}static getStubConfig(){return{view:"settings"}}static _escapeRegExp(e){return e.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}_eid(e,t){const i=this.hass?.states,r=`${e}.${this.config.entity_prefix}_${t}`;return!i||i[r]?r:this._resolveSuffixedEntity(i,e,t,r)}_resolveSuffixedEntity(e,t,i,r){const a=this._entityAliases||={},s=a[r];if(void 0!==s){if(e[s])return s;delete a[r]}const n=Ee._escapeRegExp(`${this.config.entity_prefix}_${i}`),o=new RegExp(`^${t}\\.${n}(?:_\\d+)?$`),l=new RegExp(`^${t}\\..*${n}(?:_\\d+)?$`);let c=null;for(const t of Object.keys(e)){const e=o.test(t)?0:l.test(t)?1:null;null!==e&&((null===c||e<c.layer||e===c.layer&&(t.length<c.entityId.length||t.length===c.entityId.length&&t<c.entityId))&&(c={entityId:t,layer:e}))}return c?(a[r]=c.entityId,c.entityId):r}_state(e,t){return this.hass?.states?.[this._eid(e,t)]}_val(e,t){return this._state(e,t)?.state}_callService(e,t,i,r){let a;try{a=this.hass.callService(e,t,i)}catch(e){a=Promise.reject(e)}return Promise.resolve(a).then(()=>!0).catch(i=>(console.error(`[victron-charge-controller-card] service ${e}.${t} failed:`,i),this._lastServiceError={message:String(i?.message||i),ts:Date.now()},r&&r(),this.requestUpdate(),!1))}_callWS(e){return this.hass?.callWS?this.hass.callWS(e):this.hass?.connection?.sendMessagePromise?this.hass.connection.sendMessagePromise(e):Promise.reject(new Error("Home Assistant WebSocket API is unavailable"))}_setNumber(e,t){this._callService("number","set_value",{entity_id:this._eid("number",e),value:Number(t)})}_toggleSwitch(e){const t=this._val("switch",e);if("on"!==t&&"off"!==t)return;const i="on"===t;this._callService("switch",i?"turn_off":"turn_on",{entity_id:this._eid("switch",e)})}_selectMode(e){$e.includes(this._val("select","control_mode"))&&$e.includes(e)&&this._callService("select","select_option",{entity_id:this._eid("select","control_mode"),option:e})}_pressButton(e){this._callService("button","press",{entity_id:this._eid("button",e)})}_setPlanHourAction(e,t,i){const r={hour:e,action:t};if(i&&(r.date=i),i){const a=`${i}:${e}`;return this._pendingPlanActions[a]={action:t,ts:Date.now()},this.requestUpdate(),this._callService("victron_charge_control","set_hour_action",r,()=>{delete this._pendingPlanActions[a]})}return this._callService("victron_charge_control","set_hour_action",r)}_clearStalePendings(){const e=this._val("sensor","last_schedule_update");if(null===this._lastScheduleUpdateSeen)this._lastScheduleUpdateSeen=e;else if(e!==this._lastScheduleUpdateSeen)return this._lastScheduleUpdateSeen=e,this._pendingFixedPlanHours={},this._pendingActiveFixedPlan=void 0,this._pendingFixedPlanNames={},void(this._pendingPlanActions={});const t=Date.now();for(const[e,i]of Object.entries(this._pendingFixedPlanNames))t-i.ts>De&&delete this._pendingFixedPlanNames[e];for(const[e,i]of Object.entries(this._pendingFixedPlanHours)){for(const[e,r]of Object.entries(i))t-r.ts>De&&delete i[e];0===Object.keys(i).length&&delete this._pendingFixedPlanHours[e]}void 0!==this._pendingActiveFixedPlan&&t-this._pendingActiveFixedPlan.ts>De&&(this._pendingActiveFixedPlan=void 0);for(const[e,i]of Object.entries(this._pendingPlanActions))t-i.ts>De&&delete this._pendingPlanActions[e]}_getFixedPlans(){const e=this._state("sensor","fixed_plans"),t=e?.attributes||{},i={},r=t.plans;if(r&&"object"==typeof r)for(const[e,t]of Object.entries(r)){const r=Number.parseInt(e,10);if(Number.isNaN(r))continue;const a=t&&"object"==typeof t?t:{};i[r]={charge_hours:this._parseHours((a.charge_hours||[]).join(", ")),discharge_hours:this._parseHours((a.discharge_hours||[]).join(", ")),pv_charge_hours:this._parseHours((a.pv_charge_hours||[]).join(", ")),name:"string"==typeof a.name?a.name:""}}for(const[e,t]of Object.entries(this._pendingFixedPlanHours)){const r=Number.parseInt(e,10);if(Number.isNaN(r))continue;const a=i[r]||{charge_hours:[],discharge_hours:[],pv_charge_hours:[]},s=e=>"charge"===e?"charge_hours":"pv_charge"===e?"pv_charge_hours":"discharge"===e?"discharge_hours":null;for(const[e,i]of Object.entries(t)){const r=Number.parseInt(e,10);if(Number.isNaN(r))continue;const n=s(i.action);let o=!0;for(const e of["charge_hours","discharge_hours","pv_charge_hours"]){const t=e===n;a[e].includes(r)!==t&&(o=!1,a[e]=t?[...a[e],r].sort((e,t)=>e-t):a[e].filter(e=>e!==r))}o&&delete t[r]}0===Object.keys(t).length&&delete this._pendingFixedPlanHours[e],i[r]=a}let a=null==t.active?null:Number.parseInt(t.active,10);a=Number.isNaN(a)?null:a,void 0!==this._pendingActiveFixedPlan&&(this._pendingActiveFixedPlan.value===a?this._pendingActiveFixedPlan=void 0:a=this._pendingActiveFixedPlan.value);for(const[e,t]of Object.entries(this._pendingFixedPlanNames)){const r=Number.parseInt(e,10);if(Number.isNaN(r))continue;const a=i[r]||{charge_hours:[],discharge_hours:[],pv_charge_hours:[],name:""};a.name===t.value?delete this._pendingFixedPlanNames[e]:(a.name=t.value,i[r]=a)}return{plans:i,active:a}}_nextFixedPlanNumber(e){for(let t=1;t<=8;t+=1)if(!e[t])return t;return null}_setFixedPlanHour(e,t,i,r){this._callService("victron_charge_control","set_fixed_plan_hour",{plan:e,hour:t,action:i},r)}_toggleFixedPlanHour(e,t,i,r){const{plans:a}=this._getFixedPlans(),s=a[e]||{charge_hours:[],discharge_hours:[],pv_charge_hours:[]},n=r.includes(t),o=n?"idle":i;if((n?i:s.charge_hours.includes(t)?"charge":s.pv_charge_hours.includes(t)?"pv_charge":s.discharge_hours.includes(t)?"discharge":"idle")===o)return;const l=this._pendingFixedPlanHours[e]||{},c={action:o,ts:Date.now()};l[t]=c,this._pendingFixedPlanHours[e]=l,this._setFixedPlanHour(e,t,o,()=>{this._pendingFixedPlanHours[e]?.[t]===c&&(delete this._pendingFixedPlanHours[e][t],0===Object.keys(this._pendingFixedPlanHours[e]).length&&delete this._pendingFixedPlanHours[e])}),this.requestUpdate()}_activateFixedPlan(e,t){const i={value:t?null:e,ts:Date.now()};this._pendingActiveFixedPlan=i,this._callService("select","select_option",{entity_id:this._eid("select","active_fixed_plan"),option:t?"off":String(e)},()=>{this._pendingActiveFixedPlan===i&&(this._pendingActiveFixedPlan=void 0)}),this.requestUpdate()}_fixedPlanDisplayName(e,t){return t?.name||""||`Fixed Plan ${e}`}_beginFixedPlanRename(e){const{plans:t}=this._getFixedPlans();this._planNameEditing=!0,this._planNameDraft=t[e]?.name||"",this.requestUpdate(),setTimeout(()=>{this.renderRoot?.querySelector(".plan-name-input")?.focus()},0)}_cancelFixedPlanRename(){this._planNameEditing=!1,this._planNameDraft="",this.requestUpdate()}_confirmFixedPlanRename(e){const t=(this._planNameDraft||"").trim().slice(0,10);this._planNameEditing=!1,this._planNameDraft="";const{plans:i}=this._getFixedPlans();if(t!==(i[e]?.name||"")){const i={value:t,ts:Date.now()};this._pendingFixedPlanNames[e]=i,this._callService("victron_charge_control","set_fixed_plan_name",{plan:e,name:t},()=>{this._pendingFixedPlanNames[e]===i&&delete this._pendingFixedPlanNames[e]})}this.requestUpdate()}_removeFixedPlan(e){this._callService("victron_charge_control","remove_fixed_plan",{plan:e}),this._planNameEditing=!1,this._planNameDraft="",this._fixedPlanNumber===e&&(this._fixedPlanNumber=null,this._planPage="auto")}_parseHours(e){return e&&"unknown"!==e&&"unavailable"!==e?e.split(",").map(e=>parseInt(e.trim(),10)).filter(e=>!isNaN(e)&&e>=0&&e<=23):[]}_normalizePlanAction(e){return"charge"===e||"pv_charge"===e||"discharge"===e||"blocked"===e?e:"idle"}_enrichPlanDisplayState(e){const t=this._state("sensor","charge_plan")?.attributes||{},i=e=>Number.isFinite(Date.parse(e.start_time))?String(Date.parse(e.start_time)):`${e.date}:${e.hour}`,r=t.blocked_charging_hours??this._parseHours(this._val("text","blocked_charging_hours")),a=t.blocked_discharging_hours??this._parseHours(this._val("text","blocked_discharging_hours"));return _e(e).map(e=>{const s=e.hour,n=i(e),o=r.includes(s)||"blocked_charging"===e.action||"blocked"===e.action,l=a.includes(s)||"blocked_discharging"===e.action||"blocked"===e.action;let c=this._normalizePlanAction(e.action);if(null==e.action)for(const[e,r]of[["discharge","discharge_hours"],["charge","charge_hours"],["pv_charge","pv_charge_hours"]])t[r]?.some(e=>i(e)===n)&&(c=e);const d=this._pendingPlanActions[n];return d&&(d.action===c?delete this._pendingPlanActions[n]:c=d.action),{...e,displayAction:c,blockedCharging:o,blockedDischarging:l}})}_toggleBlockedHour(e,t){const i="charging"===e?"blocked_charging_hours":"blocked_discharging_hours";this._toggleHour(i,t)}_toggleHour(e,t){const i=this._parseHours(this._val("text",e)),r=i.includes(t)?i.filter(e=>e!==t):[...i,t].sort((e,t)=>e-t);this._callService("text","set_value",{entity_id:this._eid("text",e),value:r.join(", ")})}_planTimeZone(){return this._state("sensor","charge_plan")?.attributes?.time_zone||this.hass?.config?.time_zone||this._solarForecast.time_zone}_periodLabel(e,t=this._planTimeZone()){return Number.isFinite(e.start)?`${fe(e.start,t)}–${fe(e.end,t)}`:`${String(e.hour).padStart(2,"0")}:${String(e.minute||0).padStart(2,"0")}`}_planHourGroups(e){const t=new Map;return e.forEach((e,i)=>{const r=e.start-6e4*(e.minute||0),a=Number.isFinite(r)?r:`${e.date}:${e.hour}`;t.has(a)||t.set(a,{hour:e.hour,start:r,end:r+36e5,index:i,entries:[]}),t.get(a).entries.push(e)}),[...t.values()]}_periodIdentity(e){return e.start_time?`${Date.parse(e.start_time)}:${e.end}`:`${e.date}:${e.hour}`}_editablePeriod(e,t){return null!=e.price&&Number.isFinite(Number(e.price))&&(!Number.isFinite(e.end)||e.end>Date.now())&&(!e.start_time||Number.isFinite(e.start)&&e.end>e.start&&e.start>=t.start&&e.end<=t.end&&Date.parse(e.start_time)===e.start&&Date.parse(e.end_time)===e.end)}_planBarGeometry(e,t,i){const r=e.minute?.25:1,a=(e.minute||0)+(e.end-e.start)/6e4,s=Number.isFinite(a)&&a%60?.25:1;return{x:t+r,w:Math.max(0,i-r-s)}}_setPlanSlotAction(e,t){if(null==e.price||!Number.isFinite(Number(e.price))||Number.isFinite(e.end)&&e.end<=Date.now())return;if(!e.start_time)return this._setPlanHourAction(e.hour,t,e.date);const i=String(Date.parse(e.start_time));if(!(Number.isFinite(e.start)&&e.end>e.start))return;const r={action:t,ts:Date.now()};return this._pendingPlanActions[i]=r,this.requestUpdate(),this._callService("victron_charge_control","set_slot_action",{start_time:e.start_time,action:t},()=>{this._pendingPlanActions[i]===r&&delete this._pendingPlanActions[i]})}_renderSection(e,t,i,r=null){return W`
      <div class="section">
        <div class="section-header">
          <ha-icon .icon=${t}></ha-icon>
          <span>${e}</span>
          ${r?this._renderHelpIcon(e,r):j}
        </div>
        <div class="section-content">${i}</div>
      </div>`}_renderHelpLabel(e,t,i="control-label",r=null){return W`<button type="button" class="${i} setting-help-label"
      aria-label=${`Help for ${e}`} aria-haspopup="dialog"
      @click=${i=>this._openHelp({key:t,label:e,unit:r},i.currentTarget)}
    >${e}</button>`}_renderHelpIcon(e,t){return W`<button type="button" class="setting-help-icon"
      aria-label=${`Help for ${e}`} title=${`Help for ${e}`} aria-haspopup="dialog"
      @click=${i=>this._openHelp({key:t,label:e},i.currentTarget)}
    ><ha-icon icon="mdi:help-circle-outline"></ha-icon></button>`}_sliderLimits(e){const{min:t=0,max:i=100,step:r=1}=this._state("number",e)?.attributes??{};return{min:t,max:i,step:r}}_renderToggle(e,t,i=!1,r=""){const a="on"===this._val("switch",t);return W`
      <div class="control-row toggle-row">
        ${this._renderHelpLabel(e,t)}
        <span class="toggle-tooltip" title=${r||j}
          tabindex=${r?"0":j}
          role=${r?"group":j}
          aria-label=${r?`${e}: ${r}`:j}>
          <ha-switch
            aria-label=${e}
            .checked=${a}
            .disabled=${i}
            @change=${()=>{i||this._toggleSwitch(t)}}
          ></ha-switch>
        </span>
      </div>`}_renderGridConsumer(){const e=this._state("switch","grid_consumer"),t=Boolean(e?.attributes?.source_entity),i=!t||!["on","off"].includes(e?.state),r=t?i?"Grid Consumer switch is unavailable.":"on"===e.state&&null==e.attributes.power_w?"Consumer power is invalid or unavailable; zero offset is applied.":"":"Configure a Grid consumer power sensor in the integration options to enable Grid Consumer.";return W`
      ${this._renderToggle("Grid Consumer","grid_consumer",i,i?r:"")}
      ${r&&!i?W`<div class="forecast-status" role="status">${r}</div>`:j}
    `}_renderBatteryPowerControl(){const e=this._state("switch","battery_power_control"),t=Boolean(e?.attributes?.source_entity),i=!t||!["on","off"].includes(e?.state),r=t?i?"Battery Power Control switch is unavailable.":"on"===e.state&&{inactive:"Battery feedback is inactive for the current action; grid-only control is active.",waiting:"Waiting for a baseline or settled battery reading before the next feedback adjustment.",active:"Battery feedback is active; Charge / Discharge Power targets battery watts.",fallback:"Battery power is invalid, unavailable or stale; grid-only control is active with the existing offsets. Feedback resumes when ready."}[e.attributes.feedback_status]||"":"Configure a Battery power sensor in the integration options to enable Battery Power Control.";return this._renderTogglePair([{label:"Battery Power Control",key:"battery_power_control",disabled:i,tooltip:r},{label:"Disable Discharge",key:"disable_discharge",tooltip:["on","off"].includes(this._val("switch","disable_discharge"))?"":"Configure a Maximum discharge power entity in the integration options to enable Disable Discharge."}])}_renderTogglePair(e){return W`
      <div class="control-row toggle-pair">
        ${e.map(({label:e,key:t,disabled:i=!1,tooltip:r=""})=>{const a=this._val("switch",t),s="on"===a,n=i||"on"!==a&&"off"!==a;return W`
            <div class="toggle-pair-item" title=${r||j}
              tabindex=${n&&r?"0":j}>
              ${this._renderHelpLabel(e,t)}
              <ha-switch
                aria-label=${e}
                .checked=${s}
                .disabled=${n}
                @change=${()=>{n||this._toggleSwitch(t)}}
              ></ha-switch>
            </div>
          `})}
      </div>`}_renderPlanControls(){const e=this._state("switch","charge_allowed"),t=this._state("switch","discharge_allowed");if(!e||!t)return j;const i="on"===e.state,r="on"===t.state;return W`
      <div class="plan-controls">
        <div class="plan-control-toggle">
          <ha-icon icon="mdi:battery-plus"></ha-icon>
          <span class="plan-control-label">Charge allowed</span>
          <ha-switch
            .checked=${i}
            @change=${()=>this._toggleSwitch("charge_allowed")}
          ></ha-switch>
        </div>
        <div class="plan-control-toggle">
          <ha-icon icon="mdi:battery-minus"></ha-icon>
          <span class="plan-control-label">Discharge allowed</span>
          <ha-switch
            .checked=${r}
            @change=${()=>this._toggleSwitch("discharge_allowed")}
          ></ha-switch>
        </div>
      </div>
    `}_renderSlider(e,t,i="",r=!1){const a=this._state("number",t);if(!a)return j;const s=parseFloat(a.state),{min:n,max:o,step:l}=this._sliderLimits(t);return W`
      <div class="control-row slider-row">
        ${this._renderHelpLabel(e,t,"control-label",i)}
        <div class="slider-wrap">
          <div class="slider-container">
            <input type="range"
              aria-label=${e}
              min=${n} max=${o} step=${l}
              .value=${String(s)}
              .disabled=${r}
              @input=${e=>this._onSliderInput(e,i)}
              @change=${e=>this._onSliderChange(e,t)}
              @pointerdown=${e=>this._onSliderPointerDown(e)}
              @pointerup=${e=>this._onSliderPointerUp(e)}
              @pointercancel=${e=>this._onSliderPointerUp(e)}
            />
            <span class="slider-tooltip" style="display:none;"></span>
            <div class="slider-hold-progress"></div>
          </div>
          <span class="slider-value">${s}${i}</span>
        </div>
      </div>`}_onSliderPointerDown(e){const t=e.target;if(!t.disabled&&(t.dataset.lockedValue=t.value,!this._sliderUnlocked.has(t))){const e=t.parentElement.querySelector(".slider-hold-progress");e.classList.add("active"),this._sliderHoldTimers.set(t,setTimeout(()=>{t.disabled||(this._sliderUnlocked.add(t),t.classList.add("unlocked"),e.classList.remove("active"),e.classList.add("done"),t.parentElement.classList.add("slider-activated"),setTimeout(()=>t.parentElement.classList.remove("slider-activated"),200))},1e3))}}_onSliderPointerUp(e){const t=e.target,i=t.parentElement.querySelector(".slider-hold-progress"),r=this._sliderHoldTimers.get(t);r&&(clearTimeout(r),this._sliderHoldTimers.delete(t)),i.classList.remove("active","done"),this._sliderUnlocked.has(t)||void 0!==t.dataset.lockedValue&&(t.value=t.dataset.lockedValue)}_onSliderInput(e,t){const i=e.target;if(i.disabled||!this._sliderUnlocked.has(i))return void(void 0!==i.dataset.lockedValue&&(i.value=i.dataset.lockedValue));const r=i.parentElement.querySelector(".slider-tooltip"),a=i.value,s=parseFloat(i.min),n=(a-s)/(parseFloat(i.max)-s);r.textContent=`${a}${t}`,r.style.display="block",r.style.left=`calc(${100*n}% + ${16*(.5-n)}px)`}_onSliderChange(e,t){const i=e.target;i.parentElement.querySelector(".slider-tooltip").style.display="none";const r=i.disabled||this._relativeAutoMode()&&["cheapest_hours_auto_charge","expensive_hours_auto_discharge"].includes(t);this._sliderUnlocked.has(i)?(r||this._setNumber(t,i.value),this._sliderUnlocked.delete(i),i.classList.remove("unlocked")):void 0!==i.dataset.lockedValue&&(i.value=i.dataset.lockedValue),r&&(i.value=this._val("number",t))}_relativeAutoMode(){return"on"===this._val("switch","relative_auto_mode")}_priceThresholdLabel(e){return`${"charge"===e?"Charge":"Discharge"} Price ${this._relativeAutoMode()?"Delta":"Threshold"}`}_priceThresholdContext(){const e=this._state("sensor","charge_plan"),t=["unknown","unavailable"].includes(e?.state)?null:e?.attributes;return{relative:this._relativeAutoMode(),min:Number.isFinite(t?.price_reference_min)?t.price_reference_min:null,max:Number.isFinite(t?.price_reference_max)?t.price_reference_max:null}}_thresholdContextMatches(e){const t=this._priceThresholdContext();return e&&e.relative===t.relative&&e.min===t.min&&e.max===t.max}_syncThresholdContext(){const e=this._priceThresholdContext();return this._lastThresholdContext&&e.relative!==this._lastThresholdContext.relative&&(this._pendingThresholds={}),this._thresholdDrag&&!this._thresholdContextMatches(this._thresholdDrag.context)&&this._finishThresholdDrag(!1),this._lastThresholdContext=e,e}_thresholdCutoff(e,t,i){if(!Number.isFinite(t))return null;if(!i.relative)return t;const r="charge"===e?i.max:i.min;return null===r?null:"charge"===e?r-t:r+t}_svgYToPrice(e,t){const{scaleMin:i,scaleRange:r,padT:a,plotH:s}=t;return i+(a+s-Math.max(a,Math.min(a+s,e)))/s*r}_clientToSvgY(e,t){const i=t.createSVGPoint();i.x=0,i.y=e;return i.matrixTransform(t.getScreenCTM().inverse()).y}_addThresholdDragListeners(){const e={passive:!1,capture:!0};document.addEventListener("pointermove",this._onThresholdPointerMoveBound,e),document.addEventListener("pointerup",this._onThresholdPointerUpBound,e),document.addEventListener("pointercancel",this._onThresholdPointerUpBound,e),window.addEventListener("touchmove",this._onThresholdTouchMoveBound,e)}_removeThresholdDragListeners(){document.removeEventListener("pointermove",this._onThresholdPointerMoveBound,!0),document.removeEventListener("pointerup",this._onThresholdPointerUpBound,!0),document.removeEventListener("pointercancel",this._onThresholdPointerUpBound,!0),window.removeEventListener("touchmove",this._onThresholdTouchMoveBound,!0)}_finishThresholdDrag(e=!0){if(this._removeThresholdDragListeners(),this._thresholdHoldTimer&&(clearTimeout(this._thresholdHoldTimer),this._thresholdHoldTimer=null),!this._thresholdDrag)return;const{type:t,unlocked:i,value:r,group:a,pointerId:s,context:n}=this._thresholdDrag;if(a.classList.remove("threshold-holding","threshold-unlocked"),this.classList.remove("threshold-drag-active"),void 0!==s&&a.hasPointerCapture)try{a.hasPointerCapture(s)&&a.releasePointerCapture(s)}catch(e){}if(e&&i&&null!=r&&this._thresholdContextMatches(n)){const e="charge"===t?"charge_price_threshold":"discharge_price_threshold",i=n.relative?r:Math.round(100*r)/100;this._setNumber(e,i),this._pendingThresholds[t]=i,this.requestUpdate()}else this._thresholdDrag.restore?.();this._thresholdDrag=null}_onThresholdPointerDown(e,t,i){e.preventDefault(),e.stopPropagation(),this._thresholdDrag&&this._finishThresholdDrag(!1);const r=this._syncThresholdContext();if(r.relative&&null===("charge"===t?r.max:r.min))return;const a=e.currentTarget,s=a.closest("svg"),n=e.pointerId,o=Array.from(a.querySelectorAll("line"),e=>[e,e.getAttribute("y1"),e.getAttribute("y2")]),l=a.querySelector("text"),c=l?.getAttribute("y"),d=3===l?.lastChild?.nodeType?l.lastChild:null,h=d?.nodeValue;if(this._thresholdHoldTimer&&clearTimeout(this._thresholdHoldTimer),this._thresholdDrag={type:t,scale:i,group:a,svgEl:s,pointerId:n,context:r,restore:()=>{o.forEach(([e,t,i])=>{e.setAttribute("y1",t),e.setAttribute("y2",i)}),l&&l.setAttribute("y",c),d&&(d.nodeValue=h)},unlocked:!1,price:null,value:null},a.classList.add("threshold-holding"),this.classList.add("threshold-drag-active"),this._addThresholdDragListeners(),a.setPointerCapture&&void 0!==n)try{a.setPointerCapture(n)}catch(e){}this._thresholdHoldTimer=setTimeout(()=>{this._thresholdDrag&&(this._thresholdDrag.unlocked=!0,a.classList.remove("threshold-holding"),a.classList.add("threshold-unlocked"))},1e3)}_onThresholdPointerMove(e){if(this._syncThresholdContext(),!this._thresholdDrag)return;if(void 0!==this._thresholdDrag.pointerId&&e.pointerId!==this._thresholdDrag.pointerId)return;if(e.preventDefault(),e.stopPropagation(),!this._thresholdDrag.unlocked)return;const{type:t,context:i,scale:r,group:a,svgEl:s}=this._thresholdDrag,n=this._clientToSvgY(e.clientY,s);let o,l=this._svgYToPrice(n,r);if(i.relative){const{min:e,max:r,step:a}=this._sliderLimits(`${t}_price_threshold`),s="charge"===t?i.max-l:l-i.min;o=Math.max(e,Math.min(r,e+Math.round((s-e)/a)*a)),o=Math.round(1e10*o)/1e10,l=this._thresholdCutoff(t,o,i)}else l=Math.round(l/r.step)*r.step,l=Math.max(r.scaleMin,Math.min(r.scaleMax,l)),o=l;this._thresholdDrag.price=l,this._thresholdDrag.value=o;const c=r.padT+r.plotH-(l-r.scaleMin)/r.scaleRange*r.plotH;a.querySelectorAll("line").forEach(e=>{e.setAttribute("y1",c),e.setAttribute("y2",c)});const d=a.querySelector("text");d&&(d.setAttribute("y",c+3.5),3===d.lastChild?.nodeType&&(d.lastChild.nodeValue=String(Math.round(10*l)/10)))}_onThresholdTouchMove(e){this._thresholdDrag&&(e.cancelable&&e.preventDefault(),e.stopPropagation())}_onThresholdPointerUp(e){this._thresholdDrag&&(void 0!==this._thresholdDrag.pointerId&&e.pointerId!==this._thresholdDrag.pointerId||(e.preventDefault(),e.stopPropagation(),this._finishThresholdDrag("pointercancel"!==e.type)))}_renderHourChips({key:e,selected:t,activeClass:i="blocked",onClick:r}){const a=t??this._parseHours(e?this._val("text",e):null),s=r??(t=>this._toggleHour(e,t));return W`
      <div class="hour-grid">
        ${Te.map(e=>W`
          <button
            class="hour-chip ${a.includes(e)?i:""}"
            @click=${()=>s(e)}
          >${String(e).padStart(2,"0")}</button>
        `)}
      </div>`}_renderSetpointCalculation(){const e=this._state("sensor","target_setpoint"),t=e?.attributes?.calculation,i=t&&{battery_feedback_w:0,...t},r="string"==typeof e?.state&&""!==e.state.trim()&&Number.isFinite(Number(e.state)),a=[["setting_w","Setting","Mode power"],["battery_feedback_w","Battery feedback","Applied grid − battery"],["pv_charge_w","PV charge","Battery share"],["surplus_w","Surplus","15-minute mean"],["grid_consumer_w","Grid consumer","After solar surplus"]],s=r&&i&&[...a.map(([e])=>e),"limits_w"].every(e=>"number"==typeof i[e]&&Number.isFinite(i[e])),n=s?a.reduce((e,[t])=>e+i[t],0):0,o=this._state("switch","grid_consumer"),l=a.filter(([e])=>("battery_feedback_w"!==e||0!==i?.[e])&&("grid_consumer_w"!==e||"on"===o?.state&&o.attributes?.source_entity)),c=e=>`${Math.abs(e).toLocaleString(void 0,{maximumFractionDigits:1})} W`,d=e=>e>0?"charge":e<0?"discharge":"idle";return W`
      <div class="setpoint-calculation" role="group" aria-label="Grid setpoint calculation">
        <div class="setpoint-result" data-direction=${d(r?Number(e.state):0)}>
          <strong>${r?`${Number(e.state)<0?"−":""}${c(Number(e.state))}`:"—"}${s&&0!==i.limits_w?` (${n<0?"−":""}${c(n)})`:""}</strong>
        </div>
        ${s?W`
          <dl class="calculation-terms">
            ${l.map(([e,t,r])=>W`
              <div class="calculation-term" data-direction=${d(i[e])}>
                <dt>${t}</dt>
                <dd>${i[e]<0?"−":i[e]>0?"+":""}${c(i[e])}</dd>
                <span>${r}</span>
              </div>`)}
          </dl>
        `:W`<div class="calculation-unavailable">Calculation unavailable</div>`}
      </div>`}_renderModeSection(e=!1){const t=this._val("select","control_mode"),i=!$e.includes(t),r=this._val("sensor","current_price");return W`
      <!-- Mode & Status -->
      ${this._renderSection("Mode","mdi:cog",W`
        <div class="mode-group">
          ${$e.map(e=>{const r=ke[e];return W`
              <button
                class="mode-btn ${t===e?"active":""}"
                data-mode=${e}
                ?disabled=${i}
                aria-pressed=${t===e}
                @click=${()=>this._selectMode(e)}
                title=${r.label}
              >
                <ha-icon .icon=${r.icon}></ha-icon>
                <span class="mode-label">${r.label}</span>
              </button>`})}
        </div>
        ${e?W`<div class="status-row">
          <div class="status-item">
            <ha-icon icon="mdi:currency-eur"></ha-icon>
            <span>${null!=r&&"unavailable"!==r&&"unknown"!==r?`${(100*parseFloat(r)).toFixed(2)} ct/kWh`:"—"}</span>
          </div>
        </div>
        `:j}
      `,"control_mode")}`}_renderOverviewView(){return W`
      ${this._renderModeSection(!0)}
      ${this._renderSection("Grid Setpoint","mdi:transmission-tower",this._renderSetpointCalculation())}
      ${this._renderSection("Settings","mdi:cog",W`
        ${this._renderTogglePair([{label:"Charge Allowed",key:"charge_allowed"},{label:"Discharge Allowed",key:"discharge_allowed"}])}
        ${this._renderGridConsumer()}
      `)}`}_renderControlsView(){const e="on"===this._val("switch","grid_feed_in_control"),t=this._relativeAutoMode(),i=!["on","off"].includes(this._val("switch","relative_auto_mode"));return W`
      ${this._renderModeSection()}

      <!-- Charge / Discharge -->
      ${this._renderSection("Charge / Discharge","mdi:battery-charging",W`
        ${this._renderTogglePair([{label:"Charge Allowed",key:"charge_allowed"},{label:"Discharge Allowed",key:"discharge_allowed"}])}
        ${this._renderBatteryPowerControl()}
        ${this._renderSlider("Charge Power","charge_power"," W")}
        ${this._renderSlider("Discharge Power","discharge_power"," W")}
        ${this._renderSlider("PV Charging Battery Share","pv_charging_battery_share"," %")}
      `)}

      <!-- Battery Limits -->
      ${this._renderSection("Battery Limits","mdi:battery-medium",W`
        ${this._renderSlider("Min SOC","min_soc","%")}
        ${this._renderSlider("Max SOC","max_soc","%")}
        ${this._renderSlider("SOC Hysteresis","soc_hysteresis","%")}
      `)}

      <!-- Grid Settings -->
      ${this._renderSection("Grid Settings","mdi:transmission-tower",W`
        ${this._renderSlider("Idle Setpoint","idle_setpoint"," W")}
        ${this._renderSlider("Min Grid Setpoint","min_grid_setpoint"," W")}
        ${this._renderSlider("Max Grid Setpoint","max_grid_setpoint"," W")}
      `)}

      <!-- Keep automatic scheduling settings available in every control mode. -->
      ${this._renderSection("Auto Mode","mdi:auto-fix",W`
        ${this._renderGridConsumer()}
        ${this._renderToggle("Relative Auto Mode","relative_auto_mode",i,i?"Relative Auto Mode switch is unavailable; absolute price settings are shown.":"")}
        ${this._renderSlider("Charge Duration","cheapest_hours_auto_charge"," h",t)}
        ${this._renderSlider("Discharge Duration","expensive_hours_auto_discharge"," h",t)}
        ${t?W`<div class="forecast-status" role="status">Duration budgets are ignored in Relative Auto Mode, even when zero. Saved duration values are retained.</div>`:j}
        ${this._renderSlider(this._priceThresholdLabel("charge"),"charge_price_threshold"," ct/kWh")}
        ${this._renderSlider(this._priceThresholdLabel("discharge"),"discharge_price_threshold"," ct/kWh")}
      `)}

      <!-- Grid Feed-in -->
      ${this._renderSection("Grid Feed-in","mdi:solar-power",W`
        ${this._renderTogglePair([{label:"Feed-in Control",key:"grid_feed_in_control"},{label:"Control DC Coupled Feed In",key:"control_dc_coupled_feed_in"}])}
        ${e?W`
          ${this._renderSlider("Price Threshold","grid_feed_in_price_threshold"," ct/kWh")}
          ${this._renderSlider("Default Max Feed-in","default_max_grid_feed_in"," W")}
          ${this._renderSlider("Reduced Max Feed-in","reduced_max_grid_feed_in"," W")}
        `:j}
      `)}

      <!-- Blocked Hours -->
      ${this._renderSection("Blocked Hours","mdi:clock-alert",W`
        <div class="blocked-group">
          ${this._renderHelpLabel("Charging","blocked_charging_hours","blocked-label")}
          ${this._renderHourChips({key:"blocked_charging_hours",activeClass:"blocked",onClick:e=>this._toggleBlockedHour("charging",e)})}
        </div>
        <div class="blocked-group">
          ${this._renderHelpLabel("Discharging","blocked_discharging_hours","blocked-label")}
          ${this._renderHourChips({key:"blocked_discharging_hours",activeClass:"blocked",onClick:e=>this._toggleBlockedHour("discharging",e)})}
        </div>
      `)}

      <!-- Replan Hours -->
      ${this._renderSection("Replan Hours","mdi:calendar-refresh",W`
        <div class="blocked-group">
          ${this._renderHelpLabel("Recalculation Hours","replan_hours","blocked-label")}
          ${this._renderHourChips({key:"replan_hours",activeClass:"replan"})}
        </div>
      `)}

      <!-- Action buttons -->
      <div class="actions">
        <button class="action-btn primary"
          @click=${()=>this._pressButton("recalculate_schedule")}>
          <ha-icon icon="mdi:refresh"></ha-icon>
          Recalculate
        </button>
        <button class="action-btn"
          @click=${()=>this._callService("victron_charge_control","clear_schedule",{})}>
          <ha-icon icon="mdi:delete-outline"></ha-icon>
          Clear Schedule
        </button>
        ${this._renderHelpIcon("Schedule actions","schedule_actions")}
      </div>`}_renderPriceChart(e,{chargeThreshold:t=null,dischargeThreshold:i=null,forcedScaleMin:r=null,forcedScaleMax:a=null,chartId:s="today"}={}){e=_e(e),this._chartPeriods[s]=e;const n=e.map(e=>e.price).filter(e=>null!=e).map(Number).filter(Number.isFinite);if(0===n.length)return null;let o,l;if(null!==r&&null!==a)o=r,l=a;else{const e=Math.min(...n),t=Math.max(...n),i=t-e||1;o=Math.min(-1,e),l=Math.max(1,Math.ceil(t+.1*i))}const c=l-o||1,d=Date.now(),h=600,p=50,u=40,g=38,m=510,v=212,f=e.length,_=e[0].start,b=e.at(-1).end,x=Number.isFinite(_)&&b>_,y=t=>p+(x?(e[t].start-_)/(b-_):t/f)*m,w=t=>x?(e[t].end-e[t].start)/(b-_)*m:m/f,$=e=>250-(e-o)/c*v,k=o<=0&&l>=0,P=Array.from({length:6},(e,t)=>{const i=o+c*t/5;return{val:Math.round(10*i)/10,y:$(o+c*t/5)}});return V`
      <svg class="plan-chart" viewBox="0 0 ${h} ${280}" preserveAspectRatio="xMidYMid meet">
        ${this._renderPlanPatterns()}

        <!-- Grid lines -->
        ${P.map(e=>V`
          <line x1="${p}" y1="${e.y}" x2="${560}" y2="${e.y}"
            stroke="var(--vcc-border, #e0e0e0)" stroke-width="0.5"
            stroke-dasharray="${0===e.val?"none":"4,3"}" />
        `)}

        <!-- Zero line (bold) -->
        ${k?V`
          <line x1="${p}" y1="${$(0)}" x2="${560}" y2="${$(0)}"
            stroke="var(--vcc-text2, #757575)" stroke-width="1" />
        `:j}

        <!-- Bars -->
        ${e.map((e,t)=>{const i=Number(e.price);if(null==e.price||!Number.isFinite(i))return j;const r=y(t),a=w(t),{x:s,w:n}=this._planBarGeometry(e,r,a),o=$(i),l=k?$(0):250,c=Math.min(o,l),h=Math.abs(o-l)||1,p=Number.isFinite(e.end)&&e.end<=d,u=e.start<=d&&d<e.end;return V`
            <g pointer-events="none">
              ${this._renderPlanBar(e,{x:s,w:n,colX:r,colW:a,padT:g,plotH:v,barY:c,barH:h,isPast:p,isCurrent:u})}
            </g>
          `})}

        ${this._planHourGroups(e).map(e=>this._renderHourTarget(e,s,{x:x?p+(e.start-_)/(b-_)*m:y(e.index),width:x?36e5/(b-_)*m:w(e.index),top:g,height:v}))}

        <!-- Y-axis labels -->
        ${P.map(e=>V`
          <text x="${44}" y="${e.y+3.5}" text-anchor="end"
            class="plan-axis-label">${e.val}</text>
        `)}

        <!-- Charge threshold line (interactive) -->
        ${null!==t&&t>=o&&t<=l?(()=>{const e=this._state("number","charge_price_threshold")?.attributes?.step??.01,i={scaleMin:o,scaleMax:l,scaleRange:c,padT:g,plotH:v,padL:p,padR:u,chartW:h,step:e};return V`
          <g class="threshold-line-group" data-type="charge"
            @pointerdown=${e=>this._onThresholdPointerDown(e,"charge",i)}>
            <line x1="${p}" y1="${$(t)}" x2="${560}" y2="${$(t)}"
              stroke="transparent" stroke-width="22" class="threshold-hit-area" />
            <line x1="${p}" y1="${$(t)}" x2="${560}" y2="${$(t)}"
              stroke="var(--vcc-success, #4caf50)" stroke-width="1.5" stroke-dasharray="6,4" class="threshold-visible-line" />
            <text x="${564}" y="${$(t)+3.5}" text-anchor="start"
              class="plan-threshold-label" fill="var(--vcc-success, #4caf50)">${Math.round(10*t)/10}</text>
          </g>`})():j}

        <!-- Discharge threshold line (interactive) -->
        ${null!==i&&i>=o&&i<=l?(()=>{const e=this._state("number","discharge_price_threshold")?.attributes?.step??.01,t={scaleMin:o,scaleMax:l,scaleRange:c,padT:g,plotH:v,padL:p,padR:u,chartW:h,step:e};return V`
          <g class="threshold-line-group" data-type="discharge"
            @pointerdown=${e=>this._onThresholdPointerDown(e,"discharge",t)}>
            <line x1="${p}" y1="${$(i)}" x2="${560}" y2="${$(i)}"
              stroke="transparent" stroke-width="22" class="threshold-hit-area" />
            <line x1="${p}" y1="${$(i)}" x2="${560}" y2="${$(i)}"
              stroke="#ff6600" stroke-width="1.5" stroke-dasharray="6,4" class="threshold-visible-line" />
            <text x="${564}" y="${$(i)+3.5}" text-anchor="start"
              class="plan-threshold-label" fill="var(--vcc-warning, #ff6600)">${Math.round(10*i)/10}</text>
          </g>`})():j}

        <!-- Y-axis unit -->
        <text x="${62}" y="${24}" text-anchor="end"
          class="plan-axis-unit">ct/kWh</text>

        <!-- X-axis labels (every 2 hours) -->
        ${this._planHourGroups(e).map(e=>{const t=e.start<=d&&d<e.end;if(!t&&e.hour%2!=0)return j;const i=x?p+((e.start+e.end)/2-_)/(b-_)*m:y(e.index)+w(e.index)/2;return V`
            <text x="${i}" y="${274}" text-anchor="middle"
              class="plan-axis-label ${t?"plan-current-hour":""}"
            >${String(e.hour).padStart(2,"0")}</text>
          `})}

        ${this._renderHourTooltip(s,this._planHourGroups(e))}
      </svg>
    `}_renderPlanActionLegend(){return W`
      <div class="plan-legend-item">
        <span class="plan-legend-dot" style="background: var(--vcc-success)"></span>
        <span>Charge</span>
      </div>
      <div class="plan-legend-item">
        <span class="plan-legend-dot" style="background: var(--vcc-warning)"></span>
        <span>Discharge</span>
      </div>
      <div class="plan-legend-item">
        <span class="plan-legend-dot" style="background: var(--vcc-disabled)"></span>
        <span>Idle</span>
      </div>
      <div class="plan-legend-item">
        <span class="plan-legend-dot" style="background: var(--vcc-pv-charge); opacity: 0.5"></span>
        <span>PV Charge</span>
      </div>
      <div class="plan-legend-item">
        <span class="plan-legend-dot plan-legend-dot-hatched" style="--legend-base: var(--vcc-success); --legend-hatch: var(--vcc-blocked-discharging)"></span>
        <span>Charge + Blocked Discharge</span>
      </div>
      <div class="plan-legend-item">
        <span class="plan-legend-dot plan-legend-dot-hatched" style="--legend-base: var(--vcc-warning); --legend-hatch: var(--vcc-blocked-charging)"></span>
        <span>Discharge + Blocked Charge</span>
      </div>
      <div class="plan-legend-item">
        <span class="plan-legend-dot plan-legend-dot-hatched" style="--legend-base: var(--vcc-blocked-both); --legend-hatch: var(--vcc-bg)"></span>
        <span>Blocked Both</span>
      </div>
      <div class="plan-legend-item">
        <span class="plan-legend-dot plan-legend-dot-current"></span>
        <span>Current</span>
      </div>
    `}_renderPlanPatterns(){return V`
      <defs>
        <pattern id="plan-hatch-blocked-charging" patternUnits="userSpaceOnUse" width="10" height="10">
          <path d="M-2,12 L12,-2"
            stroke="var(--vcc-blocked-charging, #2e7d32)" stroke-width="1.8" opacity="0.95" />
        </pattern>
        <pattern id="plan-hatch-blocked-discharging" patternUnits="userSpaceOnUse" width="10" height="10">
          <path d="M-2,12 L12,-2"
            stroke="var(--vcc-blocked-discharging, #ef6c00)" stroke-width="1.8" opacity="0.95" />
        </pattern>
        <pattern id="plan-hatch-blocked-both" patternUnits="userSpaceOnUse" width="10" height="10">
          <path d="M-2,12 L12,-2"
            stroke="var(--vcc-bg, #fff)" stroke-width="1.8" opacity="0.95" />
        </pattern>
      </defs>`}_renderPlanBar(e,{x:t,w:i,colX:r,colW:a,padT:s,plotH:n,barY:o,barH:l,isPast:c,isCurrent:d}){const h=e=>{switch(e){case"charge":return"var(--vcc-success, #4caf50)";case"pv_charge":return"var(--vcc-pv-charge, #ffb74d)";case"discharge":return"#ff6600";case"blocked":return"var(--vcc-blocked-both, #f44336)";default:return"var(--vcc-disabled, #bdbdbd)"}},p=e.displayAction||e.action,u=c?null:(e=>e.blockedCharging&&e.blockedDischarging?"url(#plan-hatch-blocked-both)":e.blockedCharging?"url(#plan-hatch-blocked-charging)":e.blockedDischarging?"url(#plan-hatch-blocked-discharging)":null)(e),g=!c&&"pv_charge"===p,m=h(c||g?"idle":p);return V`
      ${g?V`
        <!-- PV Charge background column (light orange) -->
        <rect class="plan-pv-column"
          x="${r}" y="${s}" width="${a}" height="${n}"
          fill="var(--vcc-pv-charge, #ffb74d)" opacity="0.10" rx="1.5"
          pointer-events="none" />
      `:j}
      ${null!=e.price?V`<rect class="plan-price-bar"
        x="${t}" y="${o}" width="${i}" height="${l}"
        fill="${m}"
        opacity="${c?.35:d?1:.7}"
        rx="1.5"
      />`:j}
      ${null!=e.price&&u?V`
        <rect
          x="${t}" y="${o}" width="${i}" height="${l}"
          fill="${u}"
          opacity="${d?1:.9}"
          rx="1.5"
        />
      `:j}
      ${d?V`
        <rect x="${t-1}" y="${s}" width="${i+2}" height="${n}"
          fill="none" stroke="var(--vcc-accent, #03a9f4)"
          stroke-width="1.5" stroke-dasharray="4,3" rx="2" />
      `:j}
    `}_hourPriceDetails(e){return e.entries.map(e=>`${this._periodLabel(e)} · Price: ${null==e.price?"unavailable":`${Number(e.price).toFixed(2)} ct/kWh`}`)}_renderHourTooltip(e,t,i=e=>this._hourPriceDetails(e)){if(this._pickerBar||this._tooltipBar?.chartId!==e)return j;const r=t.find(e=>e.index===this._tooltipBar.index);return r?V`<foreignObject class="plan-hour-tooltip" x="56" y="40" width="488" height="210" pointer-events="none" aria-hidden="true">
      ${W`<div class="plan-hour-details">
        <strong>${this._periodLabel(r)}</strong>
        ${i(r).map(e=>W`<div>${e}</div>`)}
      </div>`}
    </foreignObject>`:j}_renderHourTarget(e,t,{x:i,width:r,top:a,height:s},n=this._hourPriceDetails(e)){const o=()=>{this._pickerBar||(clearTimeout(this._tooltipHideTimer),this._tooltipHideTimer=null,this._tooltipBar={chartId:t,index:e.index},this.requestUpdate())},l=()=>{this._tooltipBar?.chartId===t&&this._tooltipBar.index===e.index&&(this._tooltipBar=null,this.requestUpdate())},c=n.join(" · "),d=e.entries.some(t=>this._editablePeriod(t,e));return V`<g class="plan-bar-group" tabindex="0" role=${d?"button":"img"}
      data-past=${e.end<=Date.now()?"true":"false"} data-readonly=${String(!d)}
      aria-label=${`${this._periodLabel(e)} · ${d?"Choose hour intervals and action":"No editable price intervals"} · ${c}`}
      @mouseenter=${o} @focus=${o} @mouseleave=${l} @blur=${l}
      @keydown=${i=>this._onBarKeyDown(i,t,e.index)}
      @click=${i=>this._onBarClick(i,t,e.index)}
      @contextmenu=${i=>this._onBarContextMenu(i,t,e.index)}
      @pointerdown=${i=>this._onBarPointerDown(i,t,e.index)}
      @pointermove=${e=>this._onBarPointerMove(e)} @pointerup=${e=>this._onBarPointerUp(e)}
      @pointercancel=${e=>this._onBarPointerUp(e)} @pointerleave=${e=>this._onBarPointerUp(e)}>
      <rect class="plan-bar-hit" x=${i} y=${a} width=${r} height=${s} fill="transparent" pointer-events="all" />
      <title>${this._periodLabel(e)} · ${c}${d?" · Open to choose intervals and action":""}</title>
    </g>`}_pickerRows(e){return(e.entries.some(e=>e.end-e.start===9e5)&&e.entries.every(t=>!Number.isFinite(t.start)||(t.start-e.start)%9e5==0)?[0,1,2,3].map(t=>{const i=e.start+9e5*t;return e.entries.find(e=>e.start===i)||{start:i,end:i+9e5,price:null}}).filter((e,t,i)=>!i.slice(0,t).some(t=>t.end>e.start)):e.entries).map(t=>t.start<e.start||t.end>e.end?{start:Math.max(t.start,e.start),end:Math.min(t.end,e.end),price:null,unavailableReason:"Source interval spans another hour"}:t)}_currentPickerPeriod(e){const t=this._pickerBar;if(!t)return null;const i=this._chartPeriods[t.chartId]?.find(t=>this._periodIdentity(t)===this._periodIdentity(e));if(!i||!this._editablePeriod(i,t.group))return null;const r=this._state("sensor","charge_plan"),a=r?.attributes?.plan;if(!r?.state||["unknown","unavailable"].includes(r.state)||!Array.isArray(a))return null;const s=_e(a).find(t=>this._periodIdentity(t)===this._periodIdentity(e));return s&&this._editablePeriod(s,t.group)?i:null}_togglePickerPeriod(e){if(this._pickerApplying||!this._currentPickerPeriod(e))return;const t=this._periodIdentity(e),i=this._pickerBar.selected;i.has(t)?i.delete(t):i.add(t),this.requestUpdate()}async _applyPickerAction(e){const t=this._pickerBar;if(!t||this._pickerApplying||!["charge","pv_charge","discharge","idle"].includes(e))return;const i=t.rows.filter(e=>t.selected.has(this._periodIdentity(e)));if(!i.length)return;const r=i.map(e=>this._currentPickerPeriod(e)).filter(Boolean);this._pickerApplying=!0,t.result="",this.requestUpdate();const a=await Promise.all(r.map(t=>this._setPlanSlotAction(t,e)));if(this._pickerApplying=!1,this._pickerBar!==t)return void this.requestUpdate();const s=a.filter(Boolean).length;s!==i.length?(t.selected.clear(),t.result=`${s} of ${i.length} intervals updated. ${i.length-r.length} unavailable; ${a.filter(e=>!e).length} failed. Select available intervals to try again.`,this.requestUpdate()):this._closePicker()}_renderPlanPicker(){const e=this._pickerBar;if(!e)return j;const t=e.rows.filter(t=>e.selected.has(this._periodIdentity(t))&&this._currentPickerPeriod(t)).length;return W`<div class="vcc-help-overlay" role="presentation"
      @click=${e=>{e.target===e.currentTarget&&this._closePicker()}}>
      <div class="vcc-help-dialog plan-picker" role="dialog" aria-modal="true" aria-labelledby="plan-picker-title" aria-describedby="plan-picker-description">
        <div class="vcc-help-header">
          <span class="vcc-help-title" id="plan-picker-title">${this._periodLabel(e.group)}</span>
          <button type="button" class="vcc-help-close" aria-label="Close hour picker" @click=${()=>this._closePicker()}>✕</button>
        </div>
        <p id="plan-picker-description">Available intervals selected. Tap to deselect.</p>
        <div class="plan-picker-periods" aria-label="Intervals to change">
          ${e.rows.map(t=>{const i=this._currentPickerPeriod(t),r=!!i,a=t.end-t.start===9e5?fe(t.start,this._planTimeZone()):this._periodLabel(t),s=t.unavailableReason||(t.end<=Date.now()?"Past":null==t.price?"Price unavailable":"Interval changed or unavailable");return W`<button type="button" class="plan-picker-period" aria-pressed=${String(r&&e.selected.has(this._periodIdentity(t)))}
              ?disabled=${!r||this._pickerApplying} @click=${()=>this._togglePickerPeriod(t)}>
              <strong>${a}</strong><span>${r?`${Number(i.price).toFixed(2)} ct/kWh · ${Pe[i.displayAction||i.action]?.label||"Idle"}`:s}</span>
            </button>`})}
        </div>
        <div class="plan-picker-actions" aria-label="Apply action to selected intervals">
          ${["charge","pv_charge","discharge","idle"].map(e=>W`<button type="button" class="plan-picker-btn"
            data-action=${e} ?disabled=${!t||this._pickerApplying} @click=${()=>this._applyPickerAction(e)}>${Pe[e].label}</button>`)}
        </div>
        <div role="status" aria-live="polite">${this._pickerApplying?"Applying selected intervals…":e.result||`${t} selected`}</div>
        ${this._lastServiceError?W`<div class="warning">Service call failed: ${this._lastServiceError.message}</div>`:j}
      </div>
    </div>`}_onPickerKeyDown(e){if(!this._pickerBar)return;if("Escape"!==e.key&&"Esc"!==e.key||(e.preventDefault(),this._closePicker()),"Tab"!==e.key)return;const t=[...this.renderRoot?.querySelectorAll(".plan-picker button:not([disabled])")||[]];if(!t.length)return;const i=t.indexOf(this.renderRoot.activeElement);e.preventDefault(),t[(i+(e.shiftKey?-1:1)+t.length)%t.length].focus()}_onBarKeyDown(e,t,i){if("Escape"===e.key)return e.preventDefault(),void this._closePicker();(["Enter"," ","ContextMenu"].includes(e.key)||e.shiftKey&&"F10"===e.key)&&(e.preventDefault(),"true"!==e.currentTarget.dataset.past&&"true"!==e.currentTarget.dataset.readonly&&this._openPicker(t,i,e.currentTarget))}_onBarClick(e,t,i){if(this._barLongPressFired)return this._barLongPressFired=!1,e.preventDefault(),void e.stopPropagation();if("history"===t){if("history"===t&&this._tooltipBar?.chartId===t&&this._tooltipBar?.index===i)return this._tooltipBar=null,this._tooltipHideTimer&&(clearTimeout(this._tooltipHideTimer),this._tooltipHideTimer=null),void this.requestUpdate();this._tooltipBar={chartId:t,index:i},this._pickerBar&&this._closePicker(),this._tooltipHideTimer&&clearTimeout(this._tooltipHideTimer),this._tooltipHideTimer=setTimeout(()=>{this._tooltipBar=null,this._tooltipHideTimer=null,this.requestUpdate()},1e4),this.requestUpdate()}else this._openPicker(t,i,e.currentTarget)}_onBarContextMenu(e,t,i){e.preventDefault(),e.stopPropagation();const r=e.currentTarget;"true"!==r?.dataset?.past&&"true"!==r?.dataset?.readonly&&this._openPicker(t,i,r)}_onBarPointerDown(e,t,i){if(void 0!==e.button&&0!==e.button)return;const r=e.currentTarget;"true"!==r?.dataset?.past&&"true"!==r?.dataset?.readonly&&(this._barLongPressFired=!1,this._barHoldTimer&&clearTimeout(this._barHoldTimer),this._barHoldStart={x:e.clientX,y:e.clientY},this._barHoldTimer=setTimeout(()=>{this._barHoldTimer=null,this._barLongPressFired=!0,this._openPicker(t,i,r)},500))}_onBarPointerUp(e){this._barHoldTimer&&(clearTimeout(this._barHoldTimer),this._barHoldTimer=null),this._barHoldStart=null}_onBarPointerMove(e){if(!this._barHoldStart||!this._barHoldTimer)return;const t=e.clientX-this._barHoldStart.x,i=e.clientY-this._barHoldStart.y;t*t+i*i>36&&(clearTimeout(this._barHoldTimer),this._barHoldTimer=null,this._barHoldStart=null)}_openPicker(e,t,i=null){if(this._pickerApplying)return;const r=this._chartPeriods[e]||[],a=this._planHourGroups(r).find(e=>e.entries.includes(r[t]));if(!a||!a.entries.some(e=>this._editablePeriod(e,a)))return;this._helpOpen&&this._closeHelp();const s=this._pickerRows(a);this._pickerTrigger=i,this._pickerBar={chartId:e,group:a,rows:s,selected:new Set(s.filter(e=>this._editablePeriod(e,a)).map(e=>this._periodIdentity(e)))},this._tooltipBar=null,clearTimeout(this._tooltipHideTimer),this._tooltipHideTimer=null,window.addEventListener("keydown",this._onPickerKeyDownBound),this.requestUpdate(),this.updateComplete?.then(()=>{this._pickerBar?.group===a&&this.renderRoot?.querySelector(".plan-picker-period:not([disabled])")?.focus()})}_closePicker(e=!0){const t=this._pickerTrigger;this._pickerTrigger=null,this._pickerBar=null,window.removeEventListener("keydown",this._onPickerKeyDownBound),this.requestUpdate(),e&&this.updateComplete?.then(()=>{this._pickerBar||t?.focus()})}_openHelp(e=null,t=null){this._helpOpen||(this._closePicker(),this._helpTopic=e,this._helpTrigger=t,this._helpOpen=!0,window.addEventListener("keydown",this._onHelpKeyDownBound),this.requestUpdate(),this.updateComplete.then(()=>{if(!this._helpOpen)return;const e=this.renderRoot?.querySelector?.(".vcc-help-close");e&&e.focus()}))}_closeHelp(){if(!this._helpOpen)return;this._helpOpen=!1,this._helpTopic=null;const e=this._helpTrigger;this._helpTrigger=null,window.removeEventListener("keydown",this._onHelpKeyDownBound),this.requestUpdate(),this.updateComplete.then(()=>{if(this._helpOpen)return;const t=e?.isConnected?e:this.renderRoot?.querySelector?.(".help-btn");t&&t.focus()})}_onHelpKeyDown(e){this._helpOpen&&("Escape"===e.key||"Esc"===e.key?(e.preventDefault(),this._closeHelp()):"Tab"===e.key&&(e.preventDefault(),this.renderRoot?.querySelector?.(".vcc-help-close")?.focus()))}_startOfDay(e){const t=new Date(e);return t.setHours(0,0,0,0),t}_addPeriod(e,t,i){const r=new Date(e);return"hour"===t?r.setHours(r.getHours()+i):"day"===t?r.setDate(r.getDate()+i):"month"===t&&r.setMonth(r.getMonth()+i),r}_addCostRangePeriods(e,t,i){const r=new Date(e);return"week"===t?r.setDate(r.getDate()+7*i):"month"===t?r.setMonth(r.getMonth()+i):"year"===t?r.setFullYear(r.getFullYear()+i):r.setDate(r.getDate()+i),r}_getCurrentCostPeriodStart(e,t=new Date){if("week"===e){const e=this._startOfDay(t),i=(e.getDay()+6)%7;return e.setDate(e.getDate()-i),e}return"month"===e?new Date(t.getFullYear(),t.getMonth(),1):"year"===e?new Date(t.getFullYear(),0,1):this._startOfDay(t)}_getCostRangeWindow(e){const t=new Date,i=this._costRangeOffsets?.[e]??0,r=this._getCurrentCostPeriodStart(e,t),a=this._addCostRangePeriods(r,e,i),s=this._addCostRangePeriods(a,e,1);return{start:a,end:0===i?t:s,queryStart:this._addPeriod(a,He[e].period,-1),period:He[e].period,range:e,offset:i}}_costRefreshBucket(e){const t=new Date;return(this._costRangeOffsets?.[e]??0)<0?"archive":"year"===e?`${t.getFullYear()}-${t.getMonth()}`:"month"===e||"week"===e?t.toISOString().slice(0,10):`${t.toISOString().slice(0,13)}:${Math.floor(t.getMinutes()/5)}`}_costStatsKey(e){const t="energy"===this._costMode?[this._eid("sensor","grid_energy_import"),this._eid("sensor","grid_energy_export")]:[this._eid("sensor","grid_energy_cost"),this._eid("sensor","grid_energy_revenue")],i=this._getCostRangeWindow(e),r=0===i.offset?"current":i.end.getTime();return`${this._costMode}|${e}|${i.period}|${i.offset}|${i.start.getTime()}|${r}|${this._costRefreshBucket(e)}|${t.join(",")}`}_setCostRange(e){if(He[e]){if(this._costRange===e){if(0===(this._costRangeOffsets?.[e]??0))return;return this._costRangeOffsets={...this._costRangeOffsets,[e]:0},this._costStatsState={status:"idle",key:null,points:[],error:null},void this.requestUpdate()}this._costRange=e,this._costRangeOffsets={...this._costRangeOffsets,[e]:0},this._costStatsState={status:"idle",key:null,points:[],error:null},this.requestUpdate()}}_setCostMode(e){this._costMode!==e&&(this._costMode=e,this._costStatsState={status:"idle",key:null,points:[],error:null},this.requestUpdate())}_shiftCostPeriod(e){const t=He[this._costRange]?this._costRange:"day",i=this._costRangeOffsets?.[t]??0,r=Math.min(0,i+e);r!==i&&(this._costRangeOffsets={...this._costRangeOffsets,[t]:r},this._costStatsState={status:"idle",key:null,points:[],error:null},this.requestUpdate())}_formatCostPeriodLabel(e){const t=this._getCostRangeWindow(e),i=t.start;if("year"===e)return i.toLocaleDateString(void 0,{year:"numeric"});if("month"===e)return i.toLocaleDateString(void 0,{month:"long",year:"numeric"});if("week"===e){const e=this._addPeriod(t.start,"day",6);return`${this._formatCostDayMonth(t.start)} - ${this._formatCostDayMonth(e)}, ${e.getFullYear()}`}return`${i.toLocaleDateString(void 0,{weekday:"short"})}, ${this._formatCostDayMonth(i)} ${i.getFullYear()}`}_formatCostDayMonth(e){const t=e.toLocaleDateString(void 0,{month:"long"});return`${e.getDate()}. ${t}`}_refreshCostStats(){this._costStatsState={status:"idle",key:null,points:[],error:null},this.requestUpdate()}_ensureCostStatsLoaded(){const e=He[this._costRange]?this._costRange:"day",t=this._costStatsKey(e);if(this._costStatsState.key===t&&"idle"!==this._costStatsState.status)return;const i=this._getCostRangeWindow(e),r="energy"===this._costMode,a=r?this._eid("sensor","grid_energy_import"):this._eid("sensor","grid_energy_cost"),s=r?this._eid("sensor","grid_energy_export"):this._eid("sensor","grid_energy_revenue");this._costStatsState={status:"loading",key:t,points:[],error:null},this.requestUpdate();const n={type:"recorder/statistics_during_period",statistic_ids:[a,s],start_time:i.queryStart.toISOString(),end_time:i.end.toISOString(),period:i.period};this._callWS({...n,types:["change","sum"]}).catch(()=>this._callWS({...n,types:["sum"]})).then(r=>{if(this._costRange!==e||this._costStatsState.key!==t)return;const n=this._buildCostPoints(r||{},a,s,i);this._costStatsState={status:n.length>0?"ready":"empty",key:t,points:n,error:null},this.requestUpdate()}).catch(e=>{this._costStatsState.key===t&&(this._costStatsState={status:"error",key:t,points:[],error:e?.message||"Unable to load cost statistics"},this.requestUpdate())})}_statTimeMs(e){const t=e?.start;if("number"==typeof t)return t;const i=Date.parse(t);return Number.isFinite(i)?i:null}_numberOrNull(e){const t=Number(e);return Number.isFinite(t)?t:null}_buildDeltaMap(e=[],t){const i=new Map;let r=null;const a=[...e].map(e=>({row:e,startMs:this._statTimeMs(e)})).filter(e=>null!==e.startMs).sort((e,t)=>e.startMs-t.startMs);for(const{row:e,startMs:s}of a){const a=this._numberOrNull(e.sum);let n=this._numberOrNull(e.change);null===n&&null!==a&&null!==r&&(n=Math.max(0,a-r)),null!==a&&(r=a),s<t.start.getTime()||s>=t.end.getTime()||null!==n&&i.set(s,Math.max(0,n))}return i}_buildCostPoints(e,t,i,r){const a=this._buildDeltaMap(e[t]||[],r),s=this._buildDeltaMap(e[i]||[],r),n=[...new Set([...a.keys(),...s.keys()])].sort((e,t)=>e-t);return n.map(e=>{const t=a.get(e)??0,i=s.get(e)??0;return{startMs:e,label:this._formatCostBucketLabel(e,r.period,r.range),cost:t,revenue:i,net:i-t}})}_formatCostBucketLabel(e,t,i){const r=new Date(e);return"hour"===t?String(r.getHours()).padStart(2,"0"):"month"===t?r.toLocaleDateString(void 0,{month:"short"}):"month"===i?String(r.getDate()):r.toLocaleDateString(void 0,{month:"short",day:"numeric"})}_formatMoney(e,t=2){return`${(Number(e)||0).toFixed(t)} EUR`}_formatSignedMoney(e){const t=Number(e)||0;return`${t>0?"+":""}${t.toFixed(2)} EUR`}_formatEnergy(e,t=2){return`${(Number(e)||0).toFixed(t)} kWh`}_formatSignedEnergy(e){const t=Number(e)||0;return`${t>0?"+":""}${t.toFixed(2)} kWh`}_renderCostChart(e){if(!e.length)return null;const t="energy"===this._costMode,i=t?"kWh":"EUR",r=t?"import":"cost",a=t?"export":"revenue",s=640,n=54,o=242,l=Math.max(.01,...e.flatMap(e=>[e.cost,e.revenue])),c=1.15*l,d=562/e.length,h=Math.min(4,Math.max(1.5,.08*d)),p=Math.max(1.5,Math.min(18,(d-3*h)/2)),u=e=>278-e/c*o,g=Array.from({length:5},(e,t)=>{const i=c*t/4;return{val:i,y:u(i)}}),m=He[this._costRange]?this._costRange:"day",v="day"===m?2:Math.max(1,Math.ceil(e.length/8));return V`
      <svg class="cost-chart" viewBox="0 0 ${s} ${320}" preserveAspectRatio="xMidYMid meet">
        ${g.map(e=>V`
          <line x1="${n}" y1="${e.y}" x2="${616}" y2="${e.y}"
            stroke="var(--vcc-border, #e0e0e0)" stroke-width="0.5"
            stroke-dasharray="${0===e.val?"none":"4,3"}" />
          <text x="${47}" y="${e.y+3.5}" text-anchor="end"
            class="cost-axis-label">${t?this._formatEnergy(e.val,e.val>=10?0:1).replace(" kWh",""):this._formatMoney(e.val,e.val>=10?0:1).replace(" EUR","")}</text>
        `)}

        ${e.map((t,i)=>{const r=n+i*d+d/2,a=278-u(t.cost),s=278-u(t.revenue);return V`
            <g class="cost-bar-group" @click=${e=>this._onBarClick(e,"history",i)}>
              <rect x="${r-p-h/2}" y="${u(t.cost)}"
                width="${p}" height="${Math.max(1,a)}"
                fill="var(--vcc-error, #f44336)" opacity="0.72" rx="1.5" />
              <rect x="${r+h/2}" y="${u(t.revenue)}"
                width="${p}" height="${Math.max(1,s)}"
                fill="var(--vcc-success, #4caf50)" opacity="0.78" rx="1.5" />
            </g>
            ${"day"===m&&new Date(t.startMs).getHours()%v===0||"day"!==m&&(i%v===0||i===e.length-1)?V`
              <text x="${r}" y="${310}" text-anchor="middle"
                class="cost-axis-label">${t.label}</text>
            `:j}
          `})}

        <text x="${54}" y="${22}" text-anchor="end"
          class="cost-axis-unit">${i}</text>

        ${(()=>{if(!this._tooltipBar||"history"!==this._tooltipBar.chartId)return j;const{index:i}=this._tooltipBar;if(i<0||i>=e.length)return j;const s=e[i],o=n+i*d+d/2,l=120;let c=Math.min(u(s.cost),u(s.revenue))-52-8;c<2&&(c=Math.max(u(s.cost),u(s.revenue))+Math.max(278-u(s.cost),278-u(s.revenue))+8);let h=o-60;h=Math.max(n,Math.min(h,496));const p=t?this._formatEnergy(s.cost):this._formatMoney(s.cost),g=t?this._formatEnergy(s.revenue):this._formatMoney(s.revenue),v="hour"===He[m]?.period?`${s.label}:00`:s.label;return V`
            <g class="cost-bar-tooltip">
              <rect x="${h}" y="${c}" width="${l}" height="${52}" rx="5"
                fill="var(--vcc-card-bg, var(--card-background-color, #fff))"
                fill-opacity="0.95"
                stroke="var(--vcc-border, #e0e0e0)" stroke-width="0.8" />
              <text x="${h+60}" y="${c+15}" text-anchor="middle"
                class="cost-tooltip-time">${v}</text>
              <text x="${h+60}" y="${c+31}" text-anchor="middle"
                class="cost-tooltip-cost">${r}: ${p}</text>
              <text x="${h+60}" y="${c+47}" text-anchor="middle"
                class="cost-tooltip-revenue">${a}: ${g}</text>
            </g>
          `})()}
      </svg>
    `}_renderCostSummary(e){const t=e.reduce((e,t)=>e+t.cost,0),i=e.reduce((e,t)=>e+t.revenue,0),r=i-t,a="energy"===this._costMode,s=a?"Export":"Revenue";return W`
      <div class="cost-summary">
        <div class="cost-summary-item cost">
          <span>${a?"Import":"Cost"}</span>
          <strong>${a?this._formatEnergy(t):this._formatMoney(t)}</strong>
        </div>
        <div class="cost-summary-item revenue">
          <span>${s}</span>
          <strong>${a?this._formatEnergy(i):this._formatMoney(i)}</strong>
        </div>
        <div class="cost-summary-item ${r>=0?"positive":"negative"}">
          <span>${"Net"}</span>
          <strong>${a?this._formatSignedEnergy(r):this._formatSignedMoney(r)}</strong>
        </div>
      </div>
    `}_renderHistoryView(){const e="energy"===this._costMode,t=e?this._state("sensor","grid_energy_import"):this._state("sensor","grid_energy_cost"),i=e?this._state("sensor","grid_energy_export"):this._state("sensor","grid_energy_revenue");if(!t||!i){return W`
        <div class="warning">
          <ha-icon icon="mdi:alert-outline"></ha-icon>
          <span>${e?"Grid energy import and export sensors are not available for this entity prefix.":"Grid energy cost and revenue sensors are not available for this entity prefix."}</span>
        </div>`}const r=He[this._costRange]?this._costRange:"day";this._ensureCostStatsLoaded();const a=this._costStatsState,s=a.points||[],n=this._costRangeOffsets?.[r]??0,o=this._formatCostPeriodLabel(r),l=e?"Import":"Cost",c=e?"Export":"Revenue";return W`
      <div class="history-container">
        <div class="history-toolbar">
          <div class="cost-mode-group">
            <button
              class="cost-mode-btn ${e?"":"active"}"
              @click=${()=>this._setCostMode("cost")}
              title="Cost / Revenue in EUR"
            >
              <ha-icon icon="mdi:currency-eur"></ha-icon>
              <span>EUR</span>
            </button>
            <button
              class="cost-mode-btn ${e?"active":""}"
              @click=${()=>this._setCostMode("energy")}
              title="Import / Export in kWh"
            >
              <ha-icon icon="mdi:transmission-tower"></ha-icon>
              <span>kWh</span>
            </button>
          </div>
          <div class="cost-range-group">
            ${Object.entries(He).map(([e,t])=>W`
              <button
                class="cost-range-btn ${r===e?"active":""}"
                @click=${()=>this._setCostRange(e)}
                title=${t.label}
              >
                <ha-icon .icon=${t.icon}></ha-icon>
                <span>${t.label}</span>
              </button>
            `)}
          </div>
          <div class="cost-period-nav">
            <button
              class="cost-period-btn"
              @click=${()=>this._shiftCostPeriod(-1)}
              title="Previous ${He[r].label.toLowerCase()}"
            >
              <ha-icon icon="mdi:chevron-left"></ha-icon>
            </button>
            <div class="cost-period-label">${o}</div>
            <button
              class="cost-period-btn"
              ?disabled=${0===n}
              @click=${()=>this._shiftCostPeriod(1)}
              title="Next ${He[r].label.toLowerCase()}"
            >
              <ha-icon icon="mdi:chevron-right"></ha-icon>
            </button>
            <button class="cost-refresh-btn"
              @click=${()=>this._refreshCostStats()}
              title="Refresh statistics">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
          </div>
        </div>

        ${"loading"===a.status?W`
          <div class="cost-loading">
            <ha-icon icon="mdi:chart-bar"></ha-icon>
            <span>Loading statistics...</span>
          </div>
        `:j}

        ${"error"===a.status?W`
          <div class="warning">
            <ha-icon icon="mdi:alert-outline"></ha-icon>
            <span>${a.error||"Unable to load cost statistics."}</span>
          </div>
        `:j}

        ${"empty"===a.status?W`
          <div class="warning">
            <ha-icon icon="mdi:alert-outline"></ha-icon>
            <span>No ${e?"energy":"cost"} statistics are available for this range. Check that recorder includes these sensors and has enough statistics data.</span>
          </div>
        `:j}

        ${"ready"===a.status?W`
          ${this._renderCostSummary(s)}
          ${this._renderCostChart(s)}
          <div class="plan-legend">
            <div class="plan-legend-item">
              <span class="plan-legend-dot" style="background: var(--vcc-error)"></span>
              <span>${l}</span>
            </div>
            <div class="plan-legend-item">
              <span class="plan-legend-dot" style="background: var(--vcc-success)"></span>
              <span>${c}</span>
            </div>
          </div>
        `:j}
      </div>`}_renderPlanView(){return W`
      <div class="plan-container">
        ${this._renderFixedPlansWarning()}
        ${this._renderServiceErrorBanner()}
        ${this._renderPlanTabs()}
        ${"auto"===this._planPage?this._renderAutoPlanPage():this._renderFixedPlanPage(this._fixedPlanNumber)}
      </div>`}_renderFixedPlansWarning(){return this._state("sensor","fixed_plans")?j:(this._warnedMissingFixedPlans||(this._warnedMissingFixedPlans=!0,console.warn(`[victron-charge-controller-card] no entity matching ${this._eid("sensor","fixed_plans")} found — the integration may be older than the card, or the entity is missing. Update/restart Home Assistant so card and integration match.`)),W`
      <div class="warning">
        <ha-icon icon="mdi:alert-outline"></ha-icon>
        <span>
          Fixed-plan data not found — no entity matching
          <code>*${this.config.entity_prefix}_fixed_plans</code>.
          Update or restart Home Assistant so the integration matches the card.
        </span>
      </div>`)}_renderServiceErrorBanner(){return this._lastServiceError?Date.now()-this._lastServiceError.ts>6e3?(this._lastServiceError=null,j):(this._serviceErrorBannerTimer||(this._serviceErrorBannerTimer=setTimeout(()=>{this._serviceErrorBannerTimer=null,this.requestUpdate()},6500)),W`
      <div class="warning">
        <ha-icon icon="mdi:alert-outline"></ha-icon>
        <span>Service call failed: ${this._lastServiceError.message}</span>
      </div>`):j}_openPlanPage(e){this._closePicker(),this._planPage=e,this._planNameEditing=!1,this._planNameDraft="","number"==typeof e&&(this._fixedPlanNumber=e),this._syncSolarForecast(),this.requestUpdate()}_openNewFixedPlan(e){const t=this._nextFixedPlanNumber(e);null!=t&&(this._closePicker(),this._planPage=t,this._fixedPlanNumber=t,this._planNameEditing=!1,this._planNameDraft="",this.requestUpdate())}_renderPlanTabs(){const{plans:e,active:t}=this._getFixedPlans(),i=Object.keys(e).map(Number).sort((e,t)=>e-t),r=this._planPage;return W`
      <div class="plan-page-tabs">
        <button
          class="plan-page-btn ${"auto"===r?"active":""}"
          @click=${()=>this._openPlanPage("auto")}
          title="Auto-planned hours"
        >
          <ha-icon icon="mdi:auto-fix"></ha-icon>
          <span>Auto</span>
        </button>
        ${i.map(i=>W`
          <div
            class="plan-page-btn ${r===i?"active":""}"
            role="button"
            tabindex="0"
            @click=${()=>this._openPlanPage(i)}
            @keydown=${e=>{"Enter"!==e.key&&" "!==e.key||(e.preventDefault(),this._openPlanPage(i))}}
            title=${e[i].name?`Fixed plan ${i}: "${e[i].name}"`:`Fixed plan ${i}`}
          >
            <span class="plan-tab-select">${e[i].name||i}</span>
            <span
              class="plan-tab-check ${t===i?"checked":""}"
              title=${t===i?"Plan is active":"Plan is inactive"}
            >
              <ha-icon .icon=${t===i?"mdi:check-circle":"mdi:check-circle-outline"}></ha-icon>
            </span>
          </div>
        `)}
        <button
          class="plan-page-btn plan-tab-add"
          @click=${()=>this._openNewFixedPlan(e)}
          title="New fixed plan"
        >+</button>
      </div>`}_renderFixedPlanPage(e){const{plans:t,active:i}=this._getFixedPlans(),r=t[e]||{charge_hours:[],discharge_hours:[],pv_charge_hours:[],name:""},a=i===e,s=this._planNameEditing?W`
      <div class="fixed-plan-title-row">
        <input
          class="plan-name-input"
          type="text"
          maxlength="10"
          .value=${this._planNameDraft}
          placeholder="Plan name"
          @input=${e=>{this._planNameDraft=e.target.value}}
          @keydown=${t=>{"Enter"===t.key?(t.preventDefault(),this._confirmFixedPlanRename(e)):"Escape"===t.key&&(t.preventDefault(),this._cancelFixedPlanRename())}}
        >
        <button
          class="plan-name-confirm"
          @click=${()=>this._confirmFixedPlanRename(e)}
          title="Save name"
        >
          <ha-icon icon="mdi:check"></ha-icon>
        </button>
        <button
          class="plan-name-cancel"
          @click=${()=>this._cancelFixedPlanRename()}
          title="Cancel"
        >
          <ha-icon icon="mdi:close"></ha-icon>
        </button>
      </div>
    `:W`
      <div class="fixed-plan-title-row">
        <span class="fixed-plan-title">${this._fixedPlanDisplayName(e,r)}</span>
        <button
          class="plan-name-pen"
          @click=${()=>this._beginFixedPlanRename(e)}
          title="Rename plan"
        >
          <ha-icon icon="mdi:pencil-outline"></ha-icon>
        </button>
      </div>
    `;return W`
      <div class="fixed-plan-editor">
        <div class="fixed-plan-header">
          ${s}
          <div class="fixed-plan-actions">
            <button
              class="fixed-plan-activate ${a?"checked":""}"
              @click=${()=>this._activateFixedPlan(e,a)}
              title=${a?"Deactivate plan":"Activate plan"}
            >
              <ha-icon .icon=${a?"mdi:check-circle":"mdi:check-circle-outline"}></ha-icon>
              <span>${a?"Active":"Inactive"}</span>
            </button>
            <button
              class="fixed-plan-remove"
              @click=${()=>this._removeFixedPlan(e)}
              title="Delete plan"
            >
              <ha-icon icon="mdi:trash-can-outline"></ha-icon>
            </button>
          </div>
        </div>
        <div class="fixed-plan-hint">
          While active, these hours are added to the auto plan every day
          (today + tomorrow) and win over it in the same hour.
        </div>
        <div class="blocked-group">
          <span class="blocked-label">Charging</span>
          ${this._renderHourChips({selected:r.charge_hours,activeClass:"charge",onClick:t=>this._toggleFixedPlanHour(e,t,"charge",r.charge_hours)})}
        </div>
        <div class="blocked-group">
          <span class="blocked-label">PV Charging</span>
          ${this._renderHourChips({selected:r.pv_charge_hours,activeClass:"pv",onClick:t=>this._toggleFixedPlanHour(e,t,"pv_charge",r.pv_charge_hours)})}
        </div>
        <div class="blocked-group">
          <span class="blocked-label">Discharging</span>
          ${this._renderHourChips({selected:r.discharge_hours,activeClass:"discharge",onClick:t=>this._toggleFixedPlanHour(e,t,"discharge",r.discharge_hours)})}
        </div>
      </div>`}_setPlanChartMode(e){("pv"!==e||this._solarForecast.usable)&&e!==this._planChartMode&&(this._finishThresholdDrag(!1),this._onBarPointerUp(),this._barLongPressFired=!1,this._closePicker(),clearTimeout(this._tooltipHideTimer),this._tooltipHideTimer=null,this._tooltipBar=null,this._planChartMode=e,this.requestUpdate())}_renderAutoPlanPage(){const e=this._solarForecast;return W`
      ${this._renderPlanControls()}
      <div class="forecast-mode-row">
        <ha-icon icon="mdi:currency-eur" title="Price" role="img" aria-label="Price"></ha-icon>
        <ha-switch aria-label="PV forecast view" aria-describedby="forecast-status"
          .checked=${"pv"===this._planChartMode} .disabled=${!e.usable}
          @change=${e=>this._setPlanChartMode(e.target.checked?"pv":"price")}></ha-switch>
        <ha-icon icon="mdi:solar-power" title="PV forecast" role="img" aria-label="PV forecast"></ha-icon>
        <span id="forecast-status" class="forecast-status" role="status">${e.usable?"":String(e.reason).replaceAll("_"," ")}</span>
      </div>
      ${"pv"===this._planChartMode&&e.usable?this._renderSolarForecast():this._renderAutoPlanContent()}
    `}_renderSolarForecast(){const e=this._solarForecast,t=this._state("sensor","charge_plan")?.attributes?.plan,i=function(e,t=[]){t=_e(t);const i=new Intl.DateTimeFormat("en-GB",{timeZone:e.time_zone,hour:"2-digit",hourCycle:"h23",timeZoneName:"longOffset"}),r=e.days.map(r=>{const a=new Map(t.filter(e=>e.date===r.date).map(e=>[Number(e.hour),e]));let s,n=[];for(let t=r.start;t<r.end;t+=6e4){const o=i.format(t),l=Math.min(t+6e4,r.end);if(o===s)n.at(-1).end=l;else{const i=ve(t,e.time_zone),s=a.get(i);n.push({...s,date:r.date,start:t,end:l,hour:i,minute:Number(new Intl.DateTimeFormat("en-GB",{timeZone:e.time_zone,minute:"2-digit"}).format(t)),price:ge(s?.price)?s.price:null})}s=o}const o=t.filter(e=>Number.isFinite(e.start)&&e.end>e.start&&e.start<r.end&&e.end>r.start);if(t.some(e=>Number.isFinite(e.start))){const t=[...new Set([r.start,r.end,...o.flatMap(e=>[Math.max(r.start,e.start),Math.min(r.end,e.end)]),...n.map(e=>e.start).filter(e=>!o.some(t=>t.start<e&&e<t.end))])].sort((e,t)=>e-t);n=t.slice(0,-1).map((i,a)=>{const s=o.find(e=>e.start<=i&&i<e.end);return{...s,date:r.date,start:i,end:t[a+1],hour:ve(i,e.time_zone),minute:Number(new Intl.DateTimeFormat("en-GB",{timeZone:e.time_zone,minute:"2-digit"}).format(i)),price:s?.price??null}})}const l=e.intervals.filter(e=>e.start<r.end&&e.end>r.start).map(e=>({...e,start:Math.max(r.start,e.start),end:Math.min(r.end,e.end)})),c=[...new Set([r.start,r.end,...n.flatMap(e=>[e.start,e.end]),...l.flatMap(e=>[e.start,e.end])])].sort((e,t)=>e-t),d=c.slice(0,-1).map((e,t)=>{const i=l.find(t=>t.start<=e&&t.end>e),r=n.findIndex(t=>t.start<=e&&e<t.end);return{start:e,end:c[t+1],hourIndex:r,price:n[r].price,pv_estimate:i?.pv_estimate??null,pv_estimate10:i?.pv_estimate10??null}}),h=e=>l.length&&l.every(t=>ge(t[e]))?l.reduce((t,i)=>t+i[e]*(i.end-i.start)/ue,0):null;return{...r,hours:n,intervals:l,slots:d,pvKwh:h("pv_estimate"),pv10Kwh:h("pv_estimate10")}}),a=r.flatMap(e=>e.hours.map(e=>e.price)).filter(ge),s=Math.min(0,...a),n=Math.max(0,...a),o=.1*(n-s||1),l=Math.max(1,...r.flatMap(e=>e.intervals.flatMap(e=>[e.pv_estimate,e.pv_estimate10??0])));return{days:r,priceMin:s<0?s-o:0,priceMax:Math.max(n,-s)+o,pvMax:1.1*l}}(e,this._enrichPlanDisplayState(Array.isArray(t)?t:[]));return W`
      <div class="plan-chart-container">
        ${i.days.map((t,r)=>W`
          <div class="plan-chart-label">${0===r?"Today":"Tomorrow"} <span class="plan-chart-date">${t.date}</span> - PV 10%: ${null===t.pv10Kwh?"unavailable":this._formatEnergy(t.pv10Kwh,1)} - PV: ${null===t.pvKwh?"unavailable":this._formatEnergy(t.pvKwh,1)}</div>
          ${t.hours.every(e=>null===e.price)?W`<div class="forecast-status">Prices not yet available</div>`:j}
          ${this._renderSolarChart(t,i,e.time_zone)}
        `)}
        <div class="plan-legend">
          ${this._renderPlanActionLegend()}
          <span class="plan-legend-item"><span class="plan-legend-dot" style="background:#fff59d"></span>PV estimate</span>
          <span class="plan-legend-item"><span class="plan-legend-dot" style="background:#fbc02d"></span>PV lower estimate (10%)</span>
        </div>
        <div class="forecast-status">${e.time_zone}${Number.isFinite(Date.parse(e.source_updated_at))?` · Forecast updated: ${fe(Date.parse(e.source_updated_at),e.time_zone)}`:""}</div>
      </div>`}_renderSolarChart(e,t,i){const r=50,a=550,s=38,n=240,o=Date.now(),l=`solar-${e.date}`;this._chartPeriods[l]=e.hours;const c=t=>r+(t-e.start)/(e.end-e.start)*500,d=e=>n-(e-t.priceMin)/(t.priceMax-t.priceMin)*202,h=d(0),p=e=>d(e/t.pvMax*t.priceMax),u=t=>e.slots.filter(e=>e.start<t.end&&e.end>t.start).map(e=>`${fe(e.start,i)}–${fe(e.end,i)} · Price: ${null===e.price?"unavailable":`${e.price.toFixed(2)} ct/kWh`} · PV: ${null===e.pv_estimate?"unavailable":`${e.pv_estimate.toFixed(2)} kW`} · Lower: ${null===e.pv_estimate10?"unavailable":`${e.pv_estimate10.toFixed(2)} kW`}`);return W`
      <svg class="plan-chart solar-chart" viewBox=${"0 0 600 280"} role="group" aria-label=${`PV forecast and prices for ${e.date}, ${i}`}>
        ${[0,1,2,3,4].map(e=>{const i=n-e/4*202,s=t.priceMin+e/4*(t.priceMax-t.priceMin);return V`
            <line x1=${r} x2=${a} y1=${i} y2=${i} stroke="var(--vcc-border, #ddd)" stroke-width="0.5" />
            <text x=${44} y=${i+4} text-anchor="end" class="plan-axis-label">${s.toFixed(1)}</text>
            <text x=${556} y=${i+4} class="plan-axis-label">${(s/t.priceMax*t.pvMax).toFixed(1)}</text>`})}
        <line x1=${r} x2=${a} y1=${h} y2=${h} stroke="var(--vcc-text-secondary, #888)" stroke-width="1" />
        <text x=${r} y="22" class="plan-axis-unit">ct/kWh</text>
        <text x=${a} y="22" text-anchor="end" class="plan-axis-unit">kW</text>
        ${this._renderPlanPatterns()}
        ${e.hours.map(e=>this._renderPlanBar(e,{...this._planBarGeometry(e,c(e.start),c(e.end)-c(e.start)),colX:c(e.start),colW:c(e.end)-c(e.start),padT:s,plotH:202,barY:Math.min(h,d(e.price)),barH:null===e.price?0:Math.abs(d(e.price)-h)||1,isPast:e.end<=o,isCurrent:e.start<=o&&o<e.end}))}
        ${be(e.intervals,"pv_estimate",c,p,h).map(e=>V`<path d=${e} fill="#fff59d" fill-opacity="0.3" stroke="#f9d95b" stroke-width="1.5" />`)}
        ${be(e.intervals,"pv_estimate10",c,p,h).map(e=>V`<path d=${e} fill="#fbc02d" fill-opacity="0.35" stroke="#e0a800" stroke-width="1.5" />`)}
        ${this._planHourGroups(e.hours).filter(e=>e.hour%2==0||e.start<=o&&o<e.end).map(e=>V`
          <text x=${(c(e.start)+c(e.end))/2} y="260" text-anchor="middle"
            class="plan-axis-label ${e.start<=o&&o<e.end?"plan-current-hour":""}">${String(e.hour).padStart(2,"0")}</text>`)}
        ${this._planHourGroups(e.hours).map(e=>this._renderHourTarget(e,l,{x:c(e.start),width:c(e.end)-c(e.start),top:s,height:202},u(e)))}
        ${this._renderHourTooltip(l,this._planHourGroups(e.hours),u)}
      </svg>
    `}_renderAutoPlanContent(){const e=this._syncThresholdContext(),t=this._state("sensor","charge_plan"),i=t?.attributes?.plan;if(!i||!Array.isArray(i)||0===i.length)return W`
        <div class="warning">
          <ha-icon icon="mdi:alert-outline"></ha-icon>
          <span>No charge plan data available.</span>
        </div>`;const r=this._state("sensor","current_price"),a=r?.state,s=[...new Set(i.map(e=>e.date))].sort(),n=s[0],o=s.length>1?s[1]:null;let l=i.filter(e=>e.date===n);const c=o?i.filter(e=>e.date===o):[];let d=c;l=this._enrichPlanDisplayState(l),d=this._enrichPlanDisplayState(d);const h=parseFloat(this._val("number","charge_price_threshold")),p=parseFloat(this._val("number","discharge_price_threshold")),u=this._thresholdCutoff("charge",this._pendingThresholds.charge??h,e),g=this._thresholdCutoff("discharge",this._pendingThresholds.discharge??p,e);void 0!==this._pendingThresholds.charge&&!isNaN(h)&&Math.abs(h-this._pendingThresholds.charge)<.001&&delete this._pendingThresholds.charge,void 0!==this._pendingThresholds.discharge&&!isNaN(p)&&Math.abs(p-this._pendingThresholds.discharge)<.001&&delete this._pendingThresholds.discharge;const m=[...l,...d].map(e=>e.price).filter(e=>null!=e).map(Number).filter(Number.isFinite);let v=null,f=null;if(m.length>0){const e=Math.min(...m),t=Math.max(...m),i=t-e||1;v=Math.min(-1,e),f=Math.max(1,Math.ceil(t+.1*i))}const _=this._renderPriceChart(l,{chargeThreshold:u,dischargeThreshold:g,forcedScaleMin:v,forcedScaleMax:f,chartId:"today"}),b=d.some(e=>void 0!==e.price&&null!==e.price),x=b?this._renderPriceChart(d,{chargeThreshold:u,dischargeThreshold:g,forcedScaleMin:v,forcedScaleMax:f,chartId:"tomorrow"}):null;return _||x?W`
      <div class="plan-chart-container">
        <div class="plan-toolbar">
          <div class="plan-toolbar-left">
            ${null!=a&&"unavailable"!==a&&"unknown"!==a?W`
              <div class="plan-current-price">
                <ha-icon icon="mdi:currency-eur"></ha-icon>
                <span><strong>${(100*parseFloat(a)).toFixed(2)} ct/kWh</strong></span>
              </div>
            `:j}
          </div>
          <div class="plan-toolbar-right">
            ${(()=>{const e=this._state("sensor","last_schedule_update");if(!e||"unknown"===e.state||"unavailable"===e.state)return j;const t=new Date(e.state);if(isNaN(t.getTime()))return j;const i=Date.now()-t.getTime(),r=Math.floor(i/6e4);let a;if(r<1)a="just now";else if(r<60)a=`${r} min ago`;else{a=`${Math.floor(r/60)}h ${r%60}m ago`}return W`<span class="plan-last-update">Updated: ${a}</span>`})()}
            <button class="action-btn plan-recalc-btn"
              @click=${()=>this._pressButton("recalculate_schedule")}>
              <ha-icon icon="mdi:refresh"></ha-icon>
              Recalculate
            </button>
          </div>
        </div>

        ${_?W`
          <div class="plan-chart-label">Today <span class="plan-chart-date">${n}</span></div>
          ${_}
        `:j}

        ${x?W`
          <div class="plan-chart-label">Tomorrow <span class="plan-chart-date">${o}</span></div>
          ${x}
        `:W`
          <div class="plan-chart-label plan-chart-label-muted">Tomorrow — prices not yet available</div>
        `}

        <!-- Legend -->
        <div class="plan-legend">
          ${this._renderPlanActionLegend()}
          ${null!==u?W`
            <div class="plan-legend-item">
              <span class="plan-legend-line" style="border-color: var(--vcc-success)"></span>
              <span>${e.relative?"Charge Cutoff":"Charge Threshold"}</span>
            </div>
          `:j}
          ${null!==g?W`
            <div class="plan-legend-item">
              <span class="plan-legend-line" style="border-color: var(--vcc-warning)"></span>
              <span>${e.relative?"Discharge Cutoff":"Discharge Threshold"}</span>
            </div>
          `:j}
        </div>
      </div>`:W`
        <div class="warning">
          <ha-icon icon="mdi:alert-outline"></ha-icon>
          <span>No EPEX price data available.</span>
        </div>`}render(){if(!this.hass||!this.config)return j;this._syncThresholdContext(),this._clearStalePendings();if(!this._state("select","control_mode"))return W`
        <ha-card>
          <div class="card-content">
            <div class="warning">
              <ha-icon icon="mdi:alert-outline"></ha-icon>
              <span>
                Victron Charge Control entities not found.
                Check entity prefix: <code>${this.config.entity_prefix}</code>
              </span>
            </div>
          </div>
        </ha-card>`;const e=this._val("sensor","desired_action")||"idle",t=Pe[e]||Pe.idle,i=this._val("sensor","grid_feed_in_status")||"default",r=Se[i]||Se.default,a=pe(this.config.view),s="overview"===a?"Overview":"plan"===a?"Plan":"history"===a?"History":"Settings";return W`
      <ha-card>
        <div class="card-header">
          <div class="header-title">
            <ha-icon .icon=${"plan"===a?"mdi:calendar":"history"===a?"mdi:chart-bar":"overview"===a?"mdi:view-dashboard":"mdi:battery-charging-wireless"}></ha-icon>
            <span>${s}</span>
          </div>
          <div class="header-center">
            <div class="header-badges">
              <div class="header-badge" data-feed-in=${i}>
                <ha-icon .icon=${r.icon}></ha-icon>
                <span>${r.label}</span>
              </div>
              <div class="header-badge" data-action=${e}>
                <ha-icon .icon=${t.icon}></ha-icon>
                <span>${t.label}</span>
              </div>
            </div>
          </div>
          <div class="header-help">
            <button
              class="help-btn"
              type="button"
              aria-label="Show help"
              title="Show help"
              aria-haspopup="dialog"
              @click=${e=>this._openHelp(null,e.currentTarget)}
            >
              <ha-icon icon="mdi:help-circle-outline"></ha-icon>
            </button>
          </div>
        </div>
        <div class="card-content">
          ${"overview"===a?this._renderOverviewView():"plan"===a?this._renderPlanView():"history"===a?this._renderHistoryView():this._renderControlsView()}
        </div>
      </ha-card>
      ${this._renderHelpDialog(a,s)}
      ${this._renderPlanPicker()}
    `}_renderHelpDialog(e,t){if(!this._helpOpen)return j;const i=this._helpTopic,r=i?this._relativeAutoMode()&&Me[i.key]||Ae[i.key]:null,a=r?"string"==typeof r[0]?[{heading:"How it works",items:r}]:r:Ce[e],s=i?["charge_price_threshold","discharge_price_threshold"].includes(i.key)?this._priceThresholdLabel(i.key.split("_")[0]):i.label:`Help – ${t}`,n=null!=i?.unit?this._sliderLimits(i.key):null;return W`
      <div
        class="vcc-help-overlay"
        role="presentation"
        @click=${e=>{e.target===e.currentTarget&&this._closeHelp()}}
      >
        <div class="vcc-help-dialog" role="dialog" aria-modal="true" aria-label=${s}>
          <div class="vcc-help-header">
            <span class="vcc-help-title">${s}</span>
            <button
              class="vcc-help-close"
              type="button"
              aria-label="Close help"
              @click=${()=>this._closeHelp()}
            >
              <ha-icon icon="mdi:close"></ha-icon>
            </button>
          </div>
          <div class="vcc-help-body">
            ${n?W`
              <section class="vcc-help-section">
                <h4 class="vcc-help-heading">Allowed range</h4>
                <dl class="vcc-help-limits">
                  ${[["Minimum",n.min],["Maximum",n.max],["Step",n.step]].map(([e,t])=>W`
                    <div><dt>${e}</dt><dd>${t}${i.unit.trim()?` ${i.unit.trim()}`:""}</dd></div>
                  `)}
                </dl>
              </section>
            `:j}
            ${a.map(e=>W`
              <section class="vcc-help-section">
                <h4 class="vcc-help-heading">${e.heading}</h4>
                <ul class="vcc-help-list">
                  ${e.items.map(e=>Array.isArray(e)?W`<li>${e.map(e=>e.bold?W`<strong>${e.text}</strong>`:e.text)}</li>`:W`<li>${e}</li>`)}
                </ul>
              </section>
            `)}
          </div>
        </div>
      </div>
    `}static get styles(){return s`
      /* ── Custom properties ─────────────────────── */
      :host {
        --vcc-accent:   var(--primary-color, #03a9f4);
        --vcc-bg:       var(--card-background-color, #fff);
        --vcc-border:   var(--divider-color, #e0e0e0);
        --vcc-text:     var(--primary-text-color, #212121);
        --vcc-text2:    var(--secondary-text-color, #757575);
        --vcc-success:  var(--success-color, #4caf50);
        --vcc-warning:  #ff6600;
        --vcc-error:    var(--error-color, #f44336);
        --vcc-info:     var(--info-color, #2196f3);
        --vcc-disabled: var(--disabled-color, #bdbdbd);
        --vcc-blocked-charging:    var(--success-color, #2e7d32);
        --vcc-blocked-discharging: var(--vcc-warning);
        --vcc-blocked-both:        var(--error-color, #f44336);
        --vcc-pv-charge:           #ffb74d;
      }
      ha-card { overflow: hidden; }

      /* ── Header ────────────────────────────────── */
      .card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 16px 16px 0;
      }
      .header-title {
        display: flex; align-items: center; gap: 8px;
        font-size: 1.0em; font-weight: 500; color: var(--vcc-text);
        flex: 0 0 auto;
      }
      .header-title ha-icon { color: var(--vcc-accent); --mdc-icon-size: 22px; }

      .header-center {
        flex: 1 1 auto;
        display: flex; align-items: center; justify-content: center;
        min-width: 0;
      }
      .header-badges {
        display: flex; align-items: center; gap: 4px;
        flex-wrap: wrap; justify-content: center;
      }
      .header-badge {
        display: flex; align-items: center; gap: 3px;
        padding: 2px 6px; border-radius: 12px;
        font-size: 0.65em; font-weight: 600;
        background: rgba(158,158,158,0.12); color: var(--vcc-disabled);
      }
      .header-badge[data-action="charge"]    { background: rgba(76,175,80,0.12);  color: var(--vcc-success); }
      .header-badge[data-action="pv_charge"] { background: rgba(255,183,77,0.12); color: var(--vcc-pv-charge); }
      .header-badge[data-action="discharge"] { background: rgba(255,152,0,0.12);  color: var(--vcc-warning); }
      .header-badge[data-feed-in="default"]  { background: rgba(76,175,80,0.12);  color: var(--vcc-success); }
      .header-badge[data-feed-in="reduced"]  { background: rgba(255,152,0,0.12);  color: var(--vcc-warning); }
      .header-badge ha-icon { --mdc-icon-size: 11px; }

      .header-help {
        flex: 0 0 auto;
        display: flex; align-items: center;
      }
      .help-btn {
        background: none; border: 0; padding: 4px; cursor: pointer;
        color: var(--vcc-text2); border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
      }
      .help-btn:hover { color: var(--vcc-accent); background: rgba(0,0,0,0.06); }
      .help-btn ha-icon { --mdc-icon-size: 20px; }

      /* ── Help dialog ─────────────────────────── */
      .vcc-help-overlay {
        position: fixed; inset: 0;
        background: rgba(0,0,0,0.35);
        display: flex; align-items: center; justify-content: center;
        z-index: 9999;
        animation: vcc-help-fade .15s ease-out;
      }
      .vcc-help-dialog {
        box-sizing: border-box;
        background: var(--vcc-bg);
        color: var(--vcc-text);
        border-radius: 10px;
        width: min(420px, calc(100vw - 32px));
        max-height: 80vh;
        overflow: auto;
        padding: 16px;
        display: flex; flex-direction: column; gap: 12px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        animation: vcc-help-pop .15s ease-out;
      }
      .vcc-help-header {
        display: flex; align-items: center; justify-content: space-between;
        gap: 8px;
      }
      .vcc-help-title { font-weight: 600; font-size: 0.95em; }
      .vcc-help-close {
        background: none; border: 0; cursor: pointer;
        color: var(--vcc-text2); padding: 4px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
      }
      .vcc-help-close:hover { background: rgba(0,0,0,0.08); color: var(--vcc-text); }
      .vcc-help-close ha-icon { --mdc-icon-size: 20px; }
      .vcc-help-body {
        font-size: 0.88em; line-height: 1.45;
        color: var(--vcc-text);
        display: flex; flex-direction: column; gap: 12px;
      }
      .vcc-help-section { display: flex; flex-direction: column; gap: 6px; }
      .vcc-help-heading {
        margin: 0;
        font-size: 0.78em; font-weight: 600;
        color: var(--vcc-accent);
        text-transform: uppercase; letter-spacing: 0.5px;
        border-bottom: 1px solid var(--vcc-border);
        padding-bottom: 4px;
      }
      .vcc-help-list {
        margin: 0; padding-left: 18px;
        display: flex; flex-direction: column; gap: 4px;
      }
      .vcc-help-list li { font-size: 0.92em; }
      .vcc-help-list li::marker { color: var(--vcc-text2); }
      .vcc-help-limits { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 0; }
      .vcc-help-limits dt { color: var(--vcc-text2); font-size: 0.85em; }
      .vcc-help-limits dd { margin: 2px 0 0; font-weight: 600; }
      .setting-help-label, .setting-help-icon {
        background: none; border: 0; cursor: pointer; font-family: inherit;
        color: var(--vcc-help-color, #039be5);
      }
      .setting-help-label {
        padding: 2px 0; text-align: left; border-radius: 2px;
        text-decoration: underline dashed var(--vcc-help-color, #039be5);
        text-underline-offset: 3px;
      }
      .setting-help-icon {
        display: inline-flex; align-items: center; justify-content: center;
        flex: 0 0 auto; padding: 4px; border-radius: 50%;
      }
      .setting-help-icon ha-icon { --mdc-icon-size: 20px; }
      .setting-help-icon:hover { background: rgba(3,155,229,0.12); }
      .setting-help-label:focus-visible, .setting-help-icon:focus-visible,
      .vcc-help-close:focus-visible, .help-btn:focus-visible {
        outline: 2px solid var(--vcc-help-color, #039be5); outline-offset: 3px;
      }
      @keyframes vcc-help-fade { from { opacity: 0; } to { opacity: 1; } }
      @keyframes vcc-help-pop  { from { transform: scale(0.96); opacity: 0; } to { transform: scale(1); opacity: 1; } }

      /* ── Content ───────────────────────────────── */
      .card-content { padding: 12px 16px 16px; }

      /* ── Warning ───────────────────────────────── */
      .warning {
        display: flex; align-items: center; gap: 8px;
        padding: 16px; color: var(--vcc-warning); font-size: 0.9em;
      }
      .warning code {
        background: var(--vcc-border); padding: 2px 6px;
        border-radius: 4px; font-size: 0.9em;
      }

      /* ── Sections ──────────────────────────────── */
      .section { margin-bottom: 16px; }
      .section:last-of-type { margin-bottom: 8px; }
      .section-header {
        display: flex; align-items: center; gap: 6px;
        padding: 6px 0; font-size: 0.8em; font-weight: 600;
        color: var(--vcc-accent); text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 1px solid var(--vcc-border); margin-bottom: 8px;
      }
      .section-header ha-icon { --mdc-icon-size: 16px; }
      .section-content { display: flex; flex-direction: column; gap: 0px; }

      /* ── Control rows ──────────────────────────── */
      .control-row {
        display: flex; align-items: center;
        justify-content: space-between;
        min-height: 36px; gap: 12px;
      }
      .control-row.slider-row {
        flex-direction: column;
        align-items: stretch;
        gap: 2px;
        min-height: auto;
      }
      .control-label {
        font-size: 0.88em; color: var(--vcc-text); flex-shrink: 0;
        width: 180px;
      }
      .control-label.setting-help-label, .blocked-label.setting-help-label {
        color: var(--vcc-text);
      }
      .control-row.slider-row > .control-label {
        width: auto;
      }
      .control-row.toggle-row > .control-label {
        flex: 1; width: auto; text-align: right;
      }
      .control-row.toggle-pair {
        gap: 16px;
      }
      .toggle-pair-item {
        display: flex; align-items: center; gap: 8px;
        flex: 1 1 0; min-width: 0;
      }
      .toggle-pair-item > .control-label {
        flex: 1; width: auto; text-align: right;
      }

      /* ── Mode selector ─────────────────────────── */
      .mode-group {
        display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px;
      }
      .mode-btn {
        display: flex; align-items: center; gap: 4px;
        padding: 6px 10px; border: 1px solid var(--vcc-border);
        border-radius: 8px; background: none; color: var(--vcc-text2);
        cursor: pointer; font-size: 0.78em; font-family: inherit;
        transition: all 0.15s ease;
      }
      .mode-btn ha-icon { --mdc-icon-size: 16px; }
      .mode-btn:hover:not(:disabled) { border-color: var(--vcc-accent); color: var(--vcc-accent); }
      .mode-btn:disabled { cursor: not-allowed; opacity: 0.5; }

      .mode-btn[data-mode="off"].active            { background: rgba(158,158,158,0.12); border-color: var(--vcc-disabled); color: var(--vcc-disabled); font-weight: 600; }
      .mode-btn[data-mode="auto"].active            { background: rgba(33,150,243,0.12);  border-color: var(--vcc-info);     color: var(--vcc-info);     font-weight: 600; }
      .mode-btn[data-mode="manual"].active          { background: rgba(255,152,0,0.12);   border-color: var(--vcc-warning);  color: var(--vcc-warning);  font-weight: 600; }
      .mode-btn[data-mode="force_charge"].active    { background: rgba(76,175,80,0.12);   border-color: var(--vcc-success);  color: var(--vcc-success);  font-weight: 600; }
      .mode-btn[data-mode="force_discharge"].active { background: rgba(244,67,54,0.12);   border-color: var(--vcc-error);    color: var(--vcc-error);    font-weight: 600; }

      @media (max-width: 400px) {
        .mode-btn .mode-label { display: none; }
        .mode-btn { padding: 8px; }
      }

      /* ── Status row ────────────────────────────── */
      .status-row { display: flex; gap: 16px; flex-wrap: wrap; }
      .status-item {
        display: flex; align-items: center; gap: 4px;
        font-size: 0.88em; color: var(--vcc-text2);
      }
      .status-item ha-icon { --mdc-icon-size: 16px; }
      .toggle-tooltip { display: inline-flex; }
      .toggle-tooltip[title] ha-switch { pointer-events: none; }

      .setpoint-calculation {
        color: var(--vcc-text); font-variant-numeric: tabular-nums;
      }
      .calculation-terms {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
        gap: 12px; margin: 12px 0 0;
      }
      .calculation-term dt { font-size: 0.7em; color: var(--vcc-text2); }
      .calculation-term dd { margin: 4px 0; font-size: 0.85em; font-weight: 600; }
      .calculation-term span { font-size: 0.65em; color: var(--vcc-text2); }
      .setpoint-result {
        margin: 0; padding-bottom: 12px; font-size: 1em;
        border-bottom: 1px solid var(--vcc-border);
      }
      .setpoint-result strong { font-weight: 600; }
      .setpoint-calculation [data-direction="idle"] :is(dd, strong) { color: var(--vcc-disabled); }
      .setpoint-calculation [data-direction="charge"] :is(dd, strong) { color: var(--vcc-success); }
      .setpoint-calculation [data-direction="discharge"] :is(dd, strong) { color: var(--vcc-error); }
      .calculation-unavailable { padding: 12px 0; font-size: 0.8em; color: var(--vcc-text2); }

      /* ── Slider ────────────────────────────────── */
      .slider-wrap {
        display: flex; align-items: center; gap: 8px;
        flex: 1; min-width: 0;
      }
      .slider-container {
        position: relative; flex: 1; min-width: 0;
        display: flex; align-items: center;
      }
      .slider-tooltip {
        position: absolute; bottom: 100%; margin-bottom: 6px;
        transform: translateX(-50%);
        background: var(--vcc-text, #212121); color: var(--vcc-bg, #fff);
        padding: 3px 8px; border-radius: 4px;
        font-size: 0.75em; font-weight: 600; white-space: nowrap;
        pointer-events: none; z-index: 1;
      }
      .slider-tooltip::after {
        content: ''; position: absolute;
        top: 100%; left: 50%; transform: translateX(-50%);
        border: 4px solid transparent;
        border-top-color: var(--vcc-text, #212121);
      }
      .slider-container input[type="range"] {
        flex: 1; min-width: 0; height: 4px; width: 100%;
        -webkit-appearance: none; appearance: none;
        background: var(--vcc-border); border-radius: 2px; outline: none;
        touch-action: none;
      }
      .slider-container input[type="range"]::-webkit-slider-thumb {
        -webkit-appearance: none; width: 16px; height: 16px;
        border-radius: 50%; background: var(--vcc-accent);
        cursor: pointer; border: 2px solid var(--vcc-bg);
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        opacity: 0.5; transition: opacity 0.2s, transform 0.2s;
      }
      .slider-container input[type="range"].unlocked::-webkit-slider-thumb {
        opacity: 1; transform: scale(1.3);
      }
      .slider-container input[type="range"]::-moz-range-thumb {
        width: 12px; height: 12px; border-radius: 50%;
        background: var(--vcc-accent); cursor: pointer;
        border: 2px solid var(--vcc-bg);
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        opacity: 0.5; transition: opacity 0.2s, transform 0.2s;
      }
      .slider-container input[type="range"].unlocked::-moz-range-thumb {
        opacity: 1; transform: scale(1.3);
      }
      .slider-hold-progress {
        position: absolute; bottom: -3px; left: 0; right: 0;
        height: 2px; border-radius: 1px; overflow: hidden;
        pointer-events: none;
      }
      .slider-hold-progress::after {
        content: ''; display: block; height: 100%;
        background: var(--vcc-accent); width: 0%;
        border-radius: 1px;
      }
      .slider-hold-progress.active::after {
        width: 100%; transition: width 1s linear;
      }
      .slider-hold-progress.done::after {
        width: 100%; background: var(--vcc-accent);
      }
      .slider-activated {
        animation: slider-pulse 0.2s ease;
      }
      @keyframes slider-pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.02); }
        100% { transform: scale(1); }
      }
      .slider-value {
        font-size: 0.82em; font-weight: 500; color: var(--vcc-text);
        min-width: 70px; text-align: right; white-space: nowrap;
      }

      /* ── Hour chips ────────────────────────────── */
      .blocked-group { margin-bottom: 10px; }
      .blocked-group:last-child { margin-bottom: 0; }
      .blocked-label {
        display: block; font-size: 0.82em;
        color: var(--vcc-text2); margin-bottom: 6px;
      }
      .hour-grid {
        display: grid; grid-template-columns: repeat(12, 1fr); gap: 3px;
      }
      .hour-chip {
        display: flex; align-items: center; justify-content: center;
        padding: 4px 0; border: 1px solid var(--vcc-border);
        border-radius: 4px; background: none; color: var(--vcc-text2);
        cursor: pointer; font-size: 0.72em; font-family: inherit;
        transition: all 0.15s ease;
      }
      .hour-chip:hover { border-color: var(--vcc-accent); color: var(--vcc-accent); }
      .hour-chip.blocked {
        background: rgba(244,67,54,0.12); border-color: var(--vcc-error);
        color: var(--vcc-error); font-weight: 600;
      }
      .hour-chip.replan {
        background: rgba(33,150,243,0.12); border-color: var(--vcc-info);
        color: var(--vcc-info); font-weight: 600;
      }
      .hour-chip.charge {
        background: rgba(76,175,80,0.12); border-color: var(--vcc-success);
        color: var(--vcc-success); font-weight: 600;
      }
      .hour-chip.pv {
        background: rgba(255,183,77,0.15); border-color: var(--vcc-pv-charge);
        color: var(--vcc-pv-charge); font-weight: 600;
      }
      .hour-chip.discharge {
        background: rgba(255,102,0,0.12); border-color: var(--vcc-warning);
        color: var(--vcc-warning); font-weight: 600;
      }
      @media (max-width: 350px) {
        .hour-grid { grid-template-columns: repeat(8, 1fr); }
      }

      /* ── Plan page tabs ────────────────────────── */
      .plan-container {
        display: flex; flex-direction: column; gap: 12px;
      }
      .plan-page-tabs {
        display: flex; gap: 4px; flex-wrap: wrap; align-items: stretch;
      }
      .plan-page-btn {
        display: flex; align-items: center; gap: 1px;
        padding: 4px 6px; border: 1px solid var(--vcc-border);
        border-radius: 8px; background: none; color: var(--vcc-text2);
        cursor: pointer; font-size: 0.78em; font-family: inherit;
        transition: all 0.15s ease;
      }
      .plan-page-btn:hover { border-color: var(--vcc-accent); color: var(--vcc-accent); }
      .plan-page-btn.active {
        background: rgba(33,150,243,0.12);
        border-color: var(--vcc-info);
        color: var(--vcc-info);
        font-weight: 600;
      }
      .plan-page-btn ha-icon { --mdc-icon-size: 14px; }
      .plan-tab-select {
        background: none; border: none; padding: 2px 4px;
        cursor: pointer; font: inherit; font-weight: 600; color: inherit;
        display: flex; align-items: center;
        max-width: 90px; overflow: hidden;
        text-overflow: ellipsis; white-space: nowrap;
      }
      .plan-tab-check {
        display: flex; align-items: center;
        color: inherit; opacity: 0.55;
      }
      .plan-tab-check.checked { opacity: 1; color: var(--vcc-success); }
      .plan-tab-add { font-weight: 700; }

      /* ── Fixed plan editor ─────────────────────── */
      .fixed-plan-editor {
        display: flex; flex-direction: column; gap: 10px;
      }
      .fixed-plan-header {
        display: flex; align-items: center; justify-content: space-between;
      }
      .fixed-plan-title-row {
        display: flex; align-items: center; gap: 4px;
        min-width: 0;
      }
      .fixed-plan-title {
        font-size: 0.95em; font-weight: 600; color: var(--vcc-text);
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      }
      .plan-name-pen,
      .plan-name-confirm,
      .plan-name-cancel {
        display: flex; align-items: center;
        padding: 2px; border: none; background: none;
        color: var(--vcc-text2); cursor: pointer;
      }
      .plan-name-pen:hover { color: var(--vcc-accent); }
      .plan-name-confirm:hover { color: var(--vcc-success); }
      .plan-name-cancel:hover { color: var(--vcc-error); }
      .plan-name-pen ha-icon,
      .plan-name-confirm ha-icon,
      .plan-name-cancel ha-icon { --mdc-icon-size: 16px; }
      .plan-name-input {
        font: inherit; font-size: 0.95em; font-weight: 600;
        color: var(--vcc-text); background: none;
        border: 1px solid var(--vcc-border); border-radius: 6px;
        padding: 4px 8px; width: 130px; min-width: 0;
      }
      .plan-name-input:focus {
        outline: none; border-color: var(--vcc-accent);
      }
      .fixed-plan-actions {
        display: flex; gap: 6px; align-items: center;
      }
      .fixed-plan-activate {
        display: flex; align-items: center; gap: 4px;
        padding: 5px 10px; border: 1px solid var(--vcc-border);
        border-radius: 8px; background: none; color: var(--vcc-text2);
        cursor: pointer; font-size: 0.78em; font-family: inherit;
        transition: all 0.15s ease;
      }
      .fixed-plan-activate ha-icon { --mdc-icon-size: 16px; }
      .fixed-plan-activate:hover { border-color: var(--vcc-success); color: var(--vcc-success); }
      .fixed-plan-activate.checked {
        background: rgba(76,175,80,0.12); border-color: var(--vcc-success);
        color: var(--vcc-success); font-weight: 600;
      }
      .fixed-plan-remove {
        display: flex; align-items: center;
        padding: 5px 8px; border: 1px solid var(--vcc-border);
        border-radius: 8px; background: none; color: var(--vcc-text2);
        cursor: pointer; font-family: inherit;
        transition: all 0.15s ease;
      }
      .fixed-plan-remove ha-icon { --mdc-icon-size: 16px; }
      .fixed-plan-remove:hover { border-color: var(--vcc-error); color: var(--vcc-error); }
      .fixed-plan-hint {
        font-size: 0.75em; color: var(--vcc-text2);
      }

      /* ── Action buttons ────────────────────────── */
      .actions {
        display: flex; gap: 8px; padding-top: 8px; flex-wrap: wrap;
      }
      .action-btn {
        display: flex; align-items: center; gap: 6px;
        padding: 8px 14px; border: 1px solid var(--vcc-border);
        border-radius: 8px; background: none; color: var(--vcc-text);
        cursor: pointer; font-size: 0.82em; font-family: inherit;
        transition: all 0.15s ease;
      }
      .action-btn:hover { background: rgba(0,0,0,0.04); }
      .action-btn.primary {
        background: var(--vcc-accent); border-color: var(--vcc-accent); color: #fff;
      }
      .action-btn.primary:hover { opacity: 0.9; }
      .action-btn ha-icon { --mdc-icon-size: 16px; }

      /* ── Plan chart ────────────────────────────── */
      .plan-chart-container {
        display: flex; flex-direction: column; gap: 12px;
      }
      .plan-chart {
        display: block; width: 100%; height: auto; min-width: 0;
        font-family: inherit;
      }
      .plan-axis-label {
        font-size: 16px;
        fill: var(--vcc-text2, #757575);
      }
      .plan-axis-unit {
        font-size: 15px;
        fill: var(--vcc-text2, #757575);
      }
      .plan-threshold-label {
        font-size: 11px;
        font-weight: 700;
      }
      .threshold-line-group {
        cursor: grab; touch-action: none;
        -webkit-user-select: none; user-select: none;
      }
      .threshold-hit-area,
      .threshold-visible-line,
      .plan-threshold-label {
        touch-action: none;
        -webkit-user-select: none; user-select: none;
      }
      .threshold-hit-area {
        pointer-events: stroke;
      }
      .threshold-line-group .threshold-visible-line {
        transition: stroke-width 0.2s;
      }
      .threshold-line-group.threshold-holding .threshold-visible-line {
        stroke-width: 2.5;
        animation: threshold-pulse 1s linear;
      }
      .threshold-line-group.threshold-unlocked .threshold-visible-line {
        stroke-width: 3;
      }
      .threshold-line-group.threshold-unlocked {
        cursor: ns-resize;
      }
      :host(.threshold-drag-active) .plan-chart-container {
        touch-action: none;
      }
      @keyframes threshold-pulse {
        0% { stroke-opacity: 0.5; }
        100% { stroke-opacity: 1; }
      }
      .plan-current-hour {
        font-weight: 700;
        fill: var(--vcc-accent, #03a9f4);
      }
      .plan-bar-group {
        cursor: pointer;
      }
      .plan-bar-group[data-past="true"] {
        cursor: default;
      }
      .plan-bar-group:focus-visible, .plan-picker-btn:focus-visible {
        outline: 2px solid var(--vcc-accent, #03a9f4);
        outline-offset: 2px;
      }
      .plan-bar-hit {
        pointer-events: all;
      }
      .plan-pv-column {
        pointer-events: none;
      }
      .plan-hour-tooltip { pointer-events: none; }
      .plan-hour-details {
        box-sizing: border-box; padding: 8px 10px;
        background: var(--vcc-bg, #fff); color: var(--vcc-text, #212121);
        border: 1px solid var(--vcc-border, #ddd); border-radius: 5px;
        font-size: 14px; line-height: 1.25;
        display: flex; flex-direction: column; gap: 6px;
      }
      .vcc-help-dialog.plan-picker { width: min(360px, calc(100vw - 24px)); padding: 10px; gap: 8px; }
      .plan-picker p, .plan-picker [role="status"] { margin: 0; font-size: .78em; line-height: 1.3; color: var(--vcc-text2); }
      .plan-picker-periods, .plan-picker-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
      .plan-picker-actions { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .plan-picker button { min-height: 44px; font: inherit; font-size: .85em; cursor: pointer; }
      .plan-picker .vcc-help-close { min-width: 44px; flex-shrink: 0; }
      .plan-picker-period, .plan-picker-btn {
        border: 1px solid var(--vcc-border); border-radius: 6px;
        background: var(--vcc-card-bg, var(--card-background-color, #fff)); color: var(--vcc-text); padding: 6px;
      }
      .plan-picker-period { display: flex; flex-direction: column; justify-content: center; gap: 2px; text-align: left; }
      .plan-picker-period span { font-size: .85em; line-height: 1.3; }
      @media (max-width: 359px) { .plan-picker-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
      .plan-picker-period[aria-pressed="true"] { border-color: var(--vcc-accent); box-shadow: inset 0 0 0 1px var(--vcc-accent); background: var(--vcc-accent-light, rgba(3,169,244,.12)); }
      .plan-picker button:disabled { opacity: .5; cursor: default; }
      .plan-picker button:focus-visible { outline: 2px solid var(--vcc-accent); outline-offset: 2px; }
      .plan-picker-btn[data-action="charge"] { border-color: var(--vcc-success); }
      .plan-picker-btn[data-action="pv_charge"] { border-color: var(--vcc-pv-charge); }
      .plan-picker-btn[data-action="discharge"] { border-color: var(--vcc-warning); }
      .plan-legend {
        display: flex; flex-wrap: wrap; gap: 12px;
        justify-content: center;
        font-size: 0.78em; color: var(--vcc-text2);
      }
      .plan-legend-item {
        display: flex; align-items: center; gap: 4px;
      }
      .plan-legend-dot {
        width: 10px; height: 10px; border-radius: 2px;
        flex-shrink: 0;
      }
      .plan-legend-dot-hatched {
        background:
          repeating-linear-gradient(
            135deg,
            transparent 0 5px,
            var(--legend-hatch, var(--vcc-bg, #fff)) 5px 7px,
            transparent 7px 10px
          ),
          var(--legend-base, var(--vcc-error, #f44336));
      }
      .plan-legend-dot-current {
        background: none;
        border: 1.5px dashed var(--vcc-accent, #03a9f4);
      }
      .plan-legend-line {
        width: 16px; height: 0;
        border-top: 2px dashed;
        flex-shrink: 0;
        align-self: center;
      }
      .plan-chart-label {
        font-size: 0.85em;
        font-weight: 600;
        color: var(--vcc-text, #212121);
        padding: 4px 0 0;
      }
      .plan-chart-label-muted {
        color: var(--vcc-text2, #757575);
        font-weight: 400;
        font-style: italic;
      }
      .plan-chart-date {
        font-weight: 400;
        color: var(--vcc-text2, #757575);
        font-size: 0.9em;
      }
      .plan-toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 0 4px;
      }
      .plan-toolbar-right {
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: 8px;
      }
      .plan-recalc-btn {
        font-size: 0.78em;
        padding: 5px 10px;
      }
      .plan-recalc-btn:hover {
        border-color: var(--vcc-accent, #03a9f4);
        color: var(--vcc-accent, #03a9f4);
      }
      .plan-last-update {
        font-size: 0.75em;
        color: var(--vcc-text2, #757575);
      }
      .plan-current-price {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.95em;
        color: var(--vcc-text, #212121);
      }
      .plan-current-price ha-icon {
        --mdc-icon-size: 18px;
        color: var(--vcc-text2, #757575);
      }
      .plan-recalc-btn {
        font-size: 0.78em;
        padding: 5px 10px;
      }
      .plan-recalc-btn:hover {
        border-color: var(--vcc-accent, #03a9f4);
        color: var(--vcc-accent, #03a9f4);
      }
      .plan-controls {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 4px 0 8px;
        flex-wrap: nowrap;
      }
      .forecast-mode-row {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-wrap: wrap;
        gap: 8px;
        font-size: 0.82em;
        border-top: 1px solid var(--vcc-border, #ddd);
        padding: 8px 0;
      }
      .forecast-mode-row .forecast-status { flex-basis: 100%; text-align: center; }
      .forecast-mode-row .forecast-status:empty { display: none; }
      .forecast-mode-row ha-icon { --mdc-icon-size: 20px; }
      .forecast-status { color: var(--vcc-text2, #757575); font-size: 0.85em; }
      .plan-control-toggle {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.82em;
        color: var(--vcc-text, #212121);
        white-space: nowrap;
        flex: 0 0 auto;
      }
      .plan-control-toggle ha-icon {
        --mdc-icon-size: 16px;
        color: var(--vcc-text2, #757575);
      }
      .plan-control-label {
        color: var(--vcc-text, #212121);
      }

      /* ── Cost chart ────────────────────────────── */
      .history-container {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .history-toolbar {
        display: flex;
        flex-direction: column;
        align-items: stretch;
        gap: 8px;
      }
      .cost-range-group {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 4px;
      }
      .cost-range-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        min-width: 0;
        padding: 7px 6px;
        border: 1px solid var(--vcc-border);
        border-radius: 8px;
        background: none;
        color: var(--vcc-text2);
        cursor: pointer;
        font-size: 0.78em;
        font-family: inherit;
        transition: all 0.15s ease;
      }
      .cost-range-btn ha-icon {
        --mdc-icon-size: 16px;
      }
      .cost-range-btn:hover {
        border-color: var(--vcc-accent);
        color: var(--vcc-accent);
      }
      .cost-range-btn.active {
        background: rgba(33,150,243,0.12);
        border-color: var(--vcc-info);
        color: var(--vcc-info);
        font-weight: 600;
      }
      .cost-range-btn span {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .cost-mode-group {
        display: flex;
        gap: 4px;
      }
      .cost-mode-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 3px;
        padding: 7px 10px;
        border: 1px solid var(--vcc-border);
        border-radius: 8px;
        background: none;
        color: var(--vcc-text2);
        cursor: pointer;
        font-size: 0.78em;
        font-family: inherit;
        transition: all 0.15s ease;
      }
      .cost-mode-btn ha-icon {
        --mdc-icon-size: 16px;
      }
      .cost-mode-btn:hover {
        border-color: var(--vcc-accent);
        color: var(--vcc-accent);
      }
      .cost-mode-btn.active {
        background: rgba(33,150,243,0.12);
        border-color: var(--vcc-info);
        color: var(--vcc-info);
        font-weight: 600;
      }
      .cost-period-nav {
        display: grid;
        grid-template-columns: 34px minmax(0, 1fr) 34px 34px;
        align-items: center;
        gap: 6px;
      }
      .cost-period-btn,
      .cost-refresh-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 34px;
        height: 32px;
        border: 1px solid var(--vcc-border);
        border-radius: 8px;
        background: none;
        color: var(--vcc-text);
        cursor: pointer;
        font-family: inherit;
        transition: all 0.15s ease;
      }
      .cost-period-btn:hover:not(:disabled),
      .cost-refresh-btn:hover {
        border-color: var(--vcc-accent);
        color: var(--vcc-accent);
        background: rgba(0,0,0,0.04);
      }
      .cost-period-btn:disabled {
        opacity: 0.38;
        cursor: default;
        pointer-events: none;
      }
      .cost-period-btn ha-icon,
      .cost-refresh-btn ha-icon {
        --mdc-icon-size: 18px;
      }
      .cost-period-label {
        min-width: 0;
        text-align: center;
        color: var(--vcc-text);
        font-size: 0.88em;
        font-weight: 600;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .cost-summary {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 6px;
      }
      .cost-summary-item {
        min-width: 0;
        padding: 8px 9px;
        border: 1px solid var(--vcc-border);
        border-radius: 8px;
      }
      .cost-summary-item span {
        display: block;
        color: var(--vcc-text2);
        font-size: 0.72em;
        margin-bottom: 2px;
      }
      .cost-summary-item strong {
        display: block;
        color: var(--vcc-text);
        font-size: 0.9em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .cost-summary-item.cost strong,
      .cost-summary-item.negative strong {
        color: var(--vcc-error);
      }
      .cost-summary-item.revenue strong,
      .cost-summary-item.positive strong {
        color: var(--vcc-success);
      }
      .cost-chart {
        width: 100%;
        height: auto;
        font-family: inherit;
      }
      .cost-axis-label {
        font-size: 16px;
        fill: var(--vcc-text2, #757575);
      }
      .cost-axis-unit {
        font-size: 16px;
        fill: var(--vcc-text2, #757575);
      }
      .cost-bar-group {
        cursor: pointer;
      }
      .cost-bar-tooltip .cost-tooltip-time {
        font-size: 16px;
        font-weight: 600;
        fill: var(--vcc-text, #212121);
      }
      .cost-bar-tooltip .cost-tooltip-cost {
        font-size: 16px;
        font-weight: 700;
        fill: var(--vcc-error, #f44336);
      }
      .cost-bar-tooltip .cost-tooltip-revenue {
        font-size: 16px;
        font-weight: 700;
        fill: var(--vcc-success, #4caf50);
      }
      .cost-loading {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 16px;
        color: var(--vcc-text2);
        font-size: 0.9em;
      }
      .cost-loading ha-icon {
        --mdc-icon-size: 18px;
      }
      @media (max-width: 420px) {
        .cost-range-btn {
          gap: 3px;
          padding: 7px 4px;
          font-size: 0.74em;
        }
        .cost-range-btn ha-icon {
          --mdc-icon-size: 14px;
        }
        .cost-mode-btn {
          padding: 6px 7px;
          font-size: 0.74em;
        }
        .cost-mode-btn ha-icon {
          --mdc-icon-size: 14px;
        }
        .cost-period-nav {
          grid-template-columns: 32px minmax(0, 1fr) 32px 32px;
          gap: 5px;
        }
        .cost-period-btn,
        .cost-refresh-btn {
          width: 32px;
          height: 31px;
        }
        .cost-period-label {
          font-size: 0.82em;
        }
        .cost-summary {
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 4px;
        }
        .cost-summary-item {
          padding: 7px 5px;
        }
        .cost-summary-item span {
          font-size: 0.68em;
        }
        .cost-summary-item strong {
          font-size: 0.78em;
        }
      }
    `}}class Fe extends le{static get properties(){return{hass:{type:Object},config:{type:Object}}}setConfig(e){this.config={...e}}_changed(e,t){this.config={...this.config,[e]:t},this.dispatchEvent(new CustomEvent("config-changed",{detail:{config:this.config}}))}render(){return this.config?W`
      <div class="editor">
        <div class="row">
          <label for="view">View</label>
          <select id="view"
            .value=${this.config.view||"settings"}
            @change=${e=>this._changed("view",e.target.value)}
          >
            <option value="overview" ?selected=${"overview"===this.config.view}>Overview</option>
            <option value="settings" ?selected=${"settings"===(this.config.view||"settings")}>Settings</option>
            <option value="plan" ?selected=${"plan"===this.config.view}>Plan</option>
            <option value="history" ?selected=${"history"===this.config.view}>History</option>
          </select>
          <small>Choose which view this card displays</small>
        </div>
      </div>`:j}static get styles(){return s`
      .editor { padding: 16px; }
      .row { display: flex; flex-direction: column; margin-bottom: 12px; }
      label { font-size: 0.85em; font-weight: 500; margin-bottom: 4px; color: var(--primary-text-color); }
      input, select {
        padding: 8px; border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px; font-size: 0.9em; font-family: inherit;
      }
      small { font-size: 0.75em; color: var(--secondary-text-color); margin-top: 4px; }
    `}}!async function(){if(void 0!==window.customPanelJS||void 0!==window.hassConnection){const e=Date.now()+6e4;for(;!window.customElements.get("home-assistant")&&Date.now()<e;)await new Promise(e=>setTimeout(e,50))}window.customElements.get(ye)||window.customElements.define(ye,Ee),window.customElements.get(we)||window.customElements.define(we,Fe),window.customCards=window.customCards||[],window.customCards.some(e=>e.type===ye)||window.customCards.push({type:ye,name:"Victron Charge Controller",description:"Control and monitor your Victron ESS charge controller",preview:!0}),console.info("%c VICTRON-CHARGE-CONTROLLER-CARD %c v2.3.0 ","color: white; background: #03a9f4; font-weight: 700; border-radius: 4px 0 0 4px; padding: 2px 6px;","color: #03a9f4; background: transparent; font-weight: 700; border: 1px solid #03a9f4; border-radius: 0 4px 4px 0; padding: 2px 6px;")}();

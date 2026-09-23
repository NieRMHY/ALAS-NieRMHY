import { useState, type ComponentProps } from 'react'
import { Check, Eye, EyeOff } from 'lucide-react'
import { useApp } from '../app/context'

export { Select } from './Select'

/** 使用真实复选框承载焦点和表单语义，图标只负责呈现。 */
export function Checkbox({children, ...props}: ComponentProps<'input'>) {
  return <label className="checkbox-control"><span className="checkbox-mark"><input {...props} type="checkbox"/><Check size={13} strokeWidth={3} aria-hidden="true"/></span><span>{children}</span></label>
}

export function PasswordInput(props: ComponentProps<'input'>) {
  const [visible, setVisible] = useState(false)
  const {ui} = useApp()
  return <span className="password-control"><input {...props} type={visible ? 'text' : 'password'}/><button type="button" className="password-reveal" disabled={props.disabled} aria-label={visible ? ui('common.hidePassword') : ui('common.showPassword')} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} aria-hidden="true"/> : <Eye size={18} aria-hidden="true"/>}</button></span>
}

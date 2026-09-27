/**
 * Shared injection key for Dropdown components
 */
import type { InjectionKey } from 'vue'

export interface DropdownContext {
  close: () => void
  closeOnSelect: boolean
}

export const dropdownKey: InjectionKey<DropdownContext> = Symbol('dropdown')

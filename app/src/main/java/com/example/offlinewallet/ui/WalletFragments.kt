package com.example.offlinewallet.ui

import android.os.Bundle
import android.view.View
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.example.offlinewallet.MainActivity
import com.example.offlinewallet.R
import com.example.offlinewallet.databinding.*
import kotlinx.coroutines.launch

abstract class WalletFragment(layout: Int) : Fragment(layout) {
    protected val host get() = requireActivity() as MainActivity
    protected val controller get() = host.viewModel.controller
    override fun onViewCreated(view: View,savedInstanceState: Bundle?) {
        super.onViewCreated(view,savedInstanceState)
        bind(view)
        render(controller.state.value)
        viewLifecycleOwner.lifecycleScope.launch { viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
            controller.state.collect(::render)
        } }
    }
    protected abstract fun bind(view: View)
    protected abstract fun render(state: AppState)
}

class AuthFragment : WalletFragment(R.layout.fragment_auth) {
    private var views: FragmentAuthBinding?=null
    override fun bind(view: View) {
        val b=FragmentAuthBinding.bind(view); views=b
        b.submit.setOnClickListener {
            val password=b.password.text.toString()
            if(controller.state.value.screen==Screen.ACTIVATION) controller.activate(b.token.text.toString(),password,b.confirmation.text.toString())
            else controller.login(b.phone.text.toString(),password,b.useDevice.isChecked)
            b.password.text?.clear(); b.confirmation.text?.clear(); b.token.text?.clear()
        }
        b.switchMode.setOnClickListener { controller.navigate(if(controller.state.value.screen==Screen.ACTIVATION) Screen.LOGIN else Screen.ACTIVATION) }
    }
    override fun render(state: AppState) { views?.let { b ->
        val activation=state.screen==Screen.ACTIVATION
        b.title.setText(if(activation) R.string.activate_account else R.string.sign_in)
        b.description.setText(if(activation) R.string.activation_description else R.string.sign_in_description)
        b.tokenLayout.isVisible=activation; b.confirmationLayout.isVisible=activation; b.phoneLayout.isVisible=!activation; b.useDevice.isVisible=!activation
        b.submit.setText(if(activation) R.string.activate_account else R.string.sign_in)
        b.switchMode.setText(if(activation) R.string.sign_in else R.string.activate_account)
        b.submit.isEnabled=!state.busy; b.switchMode.isEnabled=!state.busy
    } }
    override fun onDestroyView() { views=null; super.onDestroyView() }
}
class DeviceFragment : WalletFragment(R.layout.fragment_device) {
    private var views: FragmentDeviceBinding?=null
    override fun bind(view: View) { val b=FragmentDeviceBinding.bind(view);views=b
        b.register.setOnClickListener {
            val label=b.label.text.toString()
            if(controller.state.value.devices.any { it.status!="revoked" }) host.confirm(R.string.confirm_replacement) { controller.register(label) }
            else controller.register(label)
        }
        b.checkApproval.setOnClickListener { controller.refresh() }
        b.signInAgain.setOnClickListener { controller.navigate(Screen.LOGIN) }
        b.signOut.setOnClickListener { host.confirm(R.string.confirm_logout) { controller.logout() } }
    }
    override fun render(state: AppState) { views?.let { b ->
        val device=state.devices.find { it.deviceId==state.deviceId }
        b.status.text=when { state.offline -> getString(R.string.offline_device); state.bindingRequired -> getString(R.string.device_rebind); device?.status=="pending" -> getString(R.string.pending_device); else -> getString(R.string.no_device) }
        b.signInAgain.isVisible=state.bindingRequired; b.signInAgain.isEnabled=!state.busy
        b.details.text=device?.let { getString(R.string.device_display,it.label,it.status)+"\n"+getString(R.string.device_identifier,it.deviceId,it.secretVersion) } ?: getString(R.string.device_details)
        b.register.setText(if(state.devices.any { it.status!="revoked" }) R.string.replace_device else R.string.register_device)
        b.register.isEnabled=!state.busy && !state.offline; b.checkApproval.isEnabled=!state.busy; b.signOut.isEnabled=!state.busy
    } }
    override fun onDestroyView() { views=null;super.onDestroyView() }
}
class HomeFragment : WalletFragment(R.layout.fragment_home) {
    private var views: FragmentHomeBinding?=null
    override fun bind(view: View) { val b=FragmentHomeBinding.bind(view);views=b
        b.lock.setOnClickListener { controller.lockNow() }
        b.balanceCard.setOnClickListener { controller.toggleBalance() }
        b.history.setOnClickListener { controller.navigate(Screen.HISTORY) }
        b.refresh.setOnClickListener { controller.refresh() }
    }
    override fun render(state: AppState) { views?.let { b ->
        b.greeting.text=state.profile?.let { getString(R.string.hello_name,it.name) } ?: getString(R.string.welcome)
        b.balance.text=if(state.hidden || state.locked || state.wallet==null) getString(R.string.hidden_balance) else rupees(state.wallet.summary.balancePaise)
        b.confirmationTime.text=state.wallet?.let { getString(R.string.last_confirmed,confirmedTime(it.confirmedAt)) } ?: getString(R.string.not_confirmed)
        b.balanceHint.setText(if(state.hidden) R.string.tap_to_reveal else R.string.tap_to_hide)
        b.balanceCard.contentDescription=getString(if(state.hidden) R.string.show_balance else R.string.hide_balance)
        b.balanceCard.isEnabled=!state.busy && state.wallet!=null && !state.locked
        b.lock.contentDescription=getString(if(state.lockEnabled) R.string.lock_now else R.string.set_up_lock)
        b.refresh.isEnabled=!state.busy; b.history.isEnabled=!state.busy; b.lock.isEnabled=true
    } }
    override fun onDestroyView() { views=null;super.onDestroyView() }
}
class AddMoneyFragment : WalletFragment(R.layout.fragment_add_money) {
    override fun bind(view: View) { FragmentAddMoneyBinding.bind(view) }
    override fun render(state: AppState) = Unit
}
class ProfileFragment : WalletFragment(R.layout.fragment_profile) {
    private var views: FragmentProfileBinding?=null
    override fun bind(view: View) { val b=FragmentProfileBinding.bind(view);views=b
        b.manageLock.setOnClickListener { host.manageLock() }
        b.lockNow.setOnClickListener { controller.lockNow() }
        b.replaceDevice.setOnClickListener { controller.navigate(Screen.DEVICE) }
        b.revokeDevice.setOnClickListener { host.confirm(R.string.confirm_revoke) { controller.revoke() } }
        b.signOut.setOnClickListener { host.confirm(R.string.confirm_logout) { controller.logout() } }
        b.signOutAll.setOnClickListener { host.confirm(R.string.confirm_logout) { controller.logout(true) } }
    }
    override fun render(state: AppState) { views?.let { b ->
        b.identity.text=state.profile?.name ?: getString(R.string.profile_loading)
        b.phone.text=state.profile?.let { getString(R.string.phone_confirmation,it.phone,it.phoneConfirmation) } ?: getString(R.string.profile_loading)
        b.participant.text=state.profile?.let { getString(R.string.participant_id,it.participantId) } ?: ""
        val device=state.devices.find { it.deviceId==state.deviceId }
        b.device.text=device?.let { getString(R.string.device_display,it.label,it.status) } ?: getString(if(state.offline) R.string.offline_device else R.string.no_device)
        b.deviceDetails.text=state.devices.joinToString("\n\n") { getString(R.string.device_display,it.label,it.status)+"\n"+getString(R.string.device_identifier,it.deviceId,it.secretVersion) }
        b.lockStatus.setText(if(state.lockEnabled) R.string.app_lock_on else R.string.app_lock_off)
        listOf(b.manageLock,b.lockNow,b.signOut,b.signOutAll,b.replaceDevice).forEach { it.isEnabled=!state.busy }
        b.lockNow.isEnabled=true
        b.revokeDevice.isEnabled=!state.busy && device!=null && !state.offline
    } }
    override fun onDestroyView() { views=null;super.onDestroyView() }
}
class HistoryFragment : WalletFragment(R.layout.fragment_history) {
    private var views: FragmentHistoryBinding?=null
    private var rendered: List<com.example.offlinewallet.data.WalletTransaction>?=null
    override fun bind(view: View) { val b=FragmentHistoryBinding.bind(view);views=b
        b.loadMore.setOnClickListener { controller.loadHistory() }
        b.backHome.setOnClickListener { controller.navigate(Screen.HOME) }
    }
    override fun render(state: AppState) { views?.let { b ->
        b.empty.isVisible=state.history.isEmpty()
        b.empty.text=if(state.offline) "Transaction history needs a connection." else if(!state.historyLoaded) "Load confirmed transactions when connected." else getString(R.string.history_empty)
        if(rendered!=state.history) {
            b.rows.removeAllViews()
            state.history.forEach { t -> val row=ItemTransactionBinding.inflate(layoutInflater,b.rows,false)
                row.kind.text=t.kind.replace('_',' ').replaceFirstChar { it.titlecase() }
                row.amount.text=if(t.balanceDeltaPaise!=0L) rupees(t.balanceDeltaPaise) else "Hold change: ${rupees(t.heldDeltaPaise)}"
                row.date.text=t.createdAt.replace('T',' ').substringBefore('+')
                b.rows.addView(row.root)
            }
            rendered=state.history
        }
        b.loadMore.isVisible=!state.historyLoaded || state.nextOffset<state.historyTotal
        b.loadMore.isEnabled=!state.busy && !state.offline
        b.backHome.isEnabled=!state.busy
    } }
    override fun onDestroyView() { views=null;rendered=null;super.onDestroyView() }
}
class StatusFragment : WalletFragment(R.layout.fragment_status) {
    private var views: FragmentStatusBinding?=null
    override fun bind(view: View) { val b=FragmentStatusBinding.bind(view);views=b
        b.primary.setOnClickListener {
            when { controller.state.value.locked -> host.authenticateLocally(); controller.state.value.screen==Screen.SESSION_EXPIRED -> controller.navigate(Screen.LOGIN); else -> controller.refresh() }
        }
        b.clearData.setOnClickListener { host.confirm(R.string.confirm_erase) { controller.eraseLockedData() } }
    }
    override fun render(state: AppState) { views?.let { b ->
        b.title.setText(when { state.locked -> R.string.app_locked; state.screen==Screen.SESSION_EXPIRED -> R.string.session_expired; else -> R.string.app_name })
        b.description.setText(if(state.locked) R.string.unlock_description else if(state.screen==Screen.SESSION_EXPIRED) R.string.sign_in_description else R.string.restoring)
        b.primary.setText(if(state.locked) R.string.unlock else if(state.screen==Screen.SESSION_EXPIRED) R.string.sign_in else R.string.retry)
        b.primary.isEnabled=!state.busy; b.clearData.isEnabled=!state.busy
        b.clearData.isVisible=state.locked || (state.screen==Screen.STARTUP && state.message!=null)
    } }
    override fun onDestroyView() { views=null;super.onDestroyView() }
}

#pragma once
#include <behaviortree_cpp/action_node.h>
#include <chrono>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_action/rclcpp_action.hpp>
#include <string>

namespace dori_bt {
// Callbacks retain an operation, never the BT node: late replies after halt
// cancel their own goal and cannot overwrite a subsequent operation.
template <class Action> class RosAction : public BT::StatefulActionNode {
  public:
    using Handle = rclcpp_action::ClientGoalHandle<Action>;
    struct Operation {
        bool canceled = false, done = false, accepted = false;
        typename Handle::SharedPtr handle;
        typename Handle::WrappedResult result;
    };
    RosAction(const std::string &name, const BT::NodeConfiguration &config,
              const std::string &action, double timeout)
        : BT::StatefulActionNode(name, config), timeout_(timeout) {
        node_ = config.blackboard->get<rclcpp::Node *>("node");
        client_ = rclcpp_action::create_client<Action>(node_, action);
    }
    BT::NodeStatus onStart() override {
        op_ = std::make_shared<Operation>();
        sent_ = false;
        started_ = std::chrono::steady_clock::now();
        return onRunning();
    }
    BT::NodeStatus onRunning() override {
        auto elapsed = std::chrono::duration<double>(
                           std::chrono::steady_clock::now() - started_)
                           .count();
        if (elapsed > timeout_ || (!sent_ && elapsed > 5.)) {
            onHalted();
            return BT::NodeStatus::FAILURE;
        }
        if (!sent_) {
            if (!client_->action_server_is_ready())
                return BT::NodeStatus::RUNNING;
            typename Action::Goal goal;
            if (!prepare(goal))
                return BT::NodeStatus::FAILURE;
            auto op = op_;
            auto client = client_;
            typename rclcpp_action::Client<Action>::SendGoalOptions options;
            options.goal_response_callback =
                [op, client](typename Handle::SharedPtr handle) {
                    op->handle = handle;
                    op->accepted = static_cast<bool>(handle);
                    if (!handle)
                        op->done = true;
                    else if (op->canceled)
                        client->async_cancel_goal(handle);
                };
            options.result_callback =
                [op](const typename Handle::WrappedResult &result) {
                    op->result = result;
                    op->done = true;
                };
            client_->async_send_goal(goal, options);
            sent_ = true;
        }
        if (!op_->done)
            return BT::NodeStatus::RUNNING;
        if (!op_->accepted ||
            op_->result.code != rclcpp_action::ResultCode::SUCCEEDED)
            return BT::NodeStatus::FAILURE;
        return complete(*op_->result.result) ? BT::NodeStatus::SUCCESS
                                             : BT::NodeStatus::FAILURE;
    }
    void onHalted() override {
        if (!op_)
            return;
        op_->canceled = true;
        if (op_->handle && !op_->done)
            client_->async_cancel_goal(op_->handle);
    }

  protected:
    virtual bool prepare(typename Action::Goal &) = 0;
    virtual bool complete(const typename Action::Result &) { return true; }
    rclcpp::Node *node_;

  private:
    typename rclcpp_action::Client<Action>::SharedPtr client_;
    std::shared_ptr<Operation> op_;
    bool sent_ = false;
    double timeout_;
    std::chrono::steady_clock::time_point started_;
};
} // namespace dori_bt
